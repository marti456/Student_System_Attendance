package com.example.student_attendance_app

import android.nfc.cardemulation.HostApduService
import android.os.Bundle
import android.util.Log
import java.nio.ByteBuffer
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

/**
 * HCE (Host Card Emulation) сервис.
 *
 * Работи като виртуална NFC карта — отговаря на ESP32 четеца
 * дори когато приложението е на заден план, стига екранът да е включен.
 *
 * Протокол:
 *   1. ESP32 изпраща SELECT AID APDU
 *   2. Ние отговаряме с бинарен payload: [дължина_ФН][ФН байтове][4 байта ATC][32 байта HMAC]
 *   3. ESP32 праща сглобения стринг „ФН|ATC|HMAC_hex" към FastAPI за верификация
 *
 * Комуникация с HomeActivity:
 *   Когато телефонът е докоснат до четеца, сервизът извиква tapCallback.
 *   HomeActivity задава callback-а в onResume и го изчиства в onPause.
 */
class NfcHceService : HostApduService() {

    override fun onCreate() {
        super.onCreate()
        Log.d(TAG, "HCE Service: СТАРТИРАН (В ОЧАКВАНЕ НА NFC)")
    }

    companion object {
        private const val TAG = "NfcHceService"

        /**
         * Callback към HomeActivity — уведомява UI-а веднага щом
         * телефонът е докоснат до NFC четеца и payload-ът е изпратен.
         * HomeActivity го задава в onResume() и го зачиства в onPause().
         */
        @Volatile
        var tapCallback: (() -> Unit)? = null

        /** Callback за уведомяване на HomeActivity при прекъсната връзка/грешка */
        @Volatile
        var failureCallback: (() -> Unit)? = null

        /**
         * Управлява дали телефонът да отговаря на NFC четеца.
         * HomeActivity го включва за 30 секунди при натискане на бутон.
         */
        @Volatile
        var isCheckinActive = false

        private val SELECT_HEADER = byteArrayOf(0x00, 0xA4.toByte(), 0x04, 0x00)
        private val OUR_AID       = byteArrayOf(0xA0.toByte(), 0x00, 0x00, 0x02, 0x47, 0x10, 0x01)

        private val SW_OK        = byteArrayOf(0x90.toByte(), 0x00)
        private val SW_UNKNOWN   = byteArrayOf(0x6F.toByte(), 0x00)
        private val SW_NOT_FOUND = byteArrayOf(0x6A.toByte(), 0x82.toByte())
    }

    override fun processCommandApdu(apdu: ByteArray, extras: Bundle?): ByteArray {
        val apduHex = apdu.toHexString()
        Log.d(TAG, "NFC ДОКОСВАНЕ! Получен APDU: $apduHex")

        // Ако не сме в режим "Чекиране", игнорираме докосването.
        if (!isCheckinActive) {
            Log.w(TAG, "Опит за докосване, но режимът е изключен. Игнорираме.")
            return SW_NOT_FOUND
        }

        return when {
            // Стъпка 1: Машината иска данни
            isOurSelectAid(apdu) -> {
                Log.i(TAG, "SELECT AID: Изпращаме данни...")
                handleSelectAid()
            }
            // Стъпка 2: Машината потвърждава (ACK), че е получила данните успешно
            apdu.size >= 2 && apdu[1] == 0x40.toByte() -> {
                Log.i(TAG, "ACK ПОЛУЧЕН: Машината потвърди успешно четене!")
                
                // Едва сега деактивираме режима и казваме на UI да покаже успех
                isCheckinActive = false
                tapCallback?.invoke()
                
                SW_OK
            }
            else -> {
                Log.w(TAG, "Непозната команда: $apduHex")
                SW_UNKNOWN
            }
        }
    }

    private fun handleSelectAid(): ByteArray {
        val prefs          = StudentPrefs(this)
        val facultyNumber  = prefs.facultyNumber ?: return SW_NOT_FOUND
        val hmacKeyHex     = prefs.hmacKey       ?: return SW_NOT_FOUND
        val atc            = prefs.getAndIncrementAtc()

        // 1. Факултетен номер → байтове (запазва водещите нули)
        val fnBytes   = facultyNumber.toByteArray(Charsets.UTF_8)
        val fnLength  = fnBytes.size

        // 2. HMAC-SHA256 върху "ФН|ATC"
        val message   = "$facultyNumber|$atc"
        val keyBytes  = hmacKeyHex.chunked(2).map { it.toInt(16).toByte() }.toByteArray()
        val mac       = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(keyBytes, "HmacSHA256"))
        val hmacBytes = mac.doFinal(message.toByteArray(Charsets.UTF_8)) // 32 байта

        // 3. Буфер: [1 байт дължина][ФН][4 байта ATC big-endian][32 байта HMAC]
        val buffer = ByteBuffer.allocate(1 + fnLength + 4 + 32)
        buffer.put(fnLength.toByte())
        buffer.put(fnBytes)
        buffer.putInt(atc.toInt())
        buffer.put(hmacBytes)

        Log.d(TAG, "Payload изпратен: $facultyNumber|$atc (${buffer.capacity()} байта)")

        // Вече НЕ извикваме tapCallback тук! Чакаме ACK командата (0x40).

        return buffer.array() + SW_OK
    }

    private fun isOurSelectAid(apdu: ByteArray): Boolean {
        if (apdu.size < SELECT_HEADER.size + 1 + OUR_AID.size) return false
        for (i in SELECT_HEADER.indices) {
            if (apdu[i] != SELECT_HEADER[i]) return false
        }
        val lc = apdu[SELECT_HEADER.size].toInt() and 0xFF
        if (lc != OUR_AID.size) return false
        val aidOffset = SELECT_HEADER.size + 1
        for (i in OUR_AID.indices) {
            if (apdu[aidOffset + i] != OUR_AID[i]) return false
        }
        return true
    }

    override fun onDeactivated(reason: Int) {
        Log.d(TAG, "HCE деактивиран: $reason")
        
        // Ако връзката прекъсне (reason 0 - LINK_LOSS), докато все още чакаме ACK
        if (isCheckinActive && reason == DEACTIVATION_LINK_LOSS) {
            Log.w(TAG, "⚠️ Връзката бе прекъсната преди потвърждението (ACK).")
            isCheckinActive = false
            failureCallback?.invoke()
        }
    }

    private fun ByteArray.toHexString() = joinToString(" ") { "%02X".format(it) }
}
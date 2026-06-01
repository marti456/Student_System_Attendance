package com.example.student_attendance_app

import android.content.Context
import android.nfc.cardemulation.HostApduService
import android.os.Bundle
import android.util.Log
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
 *   2. Ние отговаряме с: "ФАКТ_НОМ|ATC|HMAC" + SW 90 00
 *   3. ESP32 праща payload-а към FastAPI сървъра за верификация
 */
class NfcHceService : HostApduService() {

    override fun onCreate() {
        super.onCreate()
        Log.d(TAG, "HCE Service: СТАРТИРАН (В ОЧАКВАНЕ НА NFC)")
    }

    companion object {
        private const val TAG = "NfcHceService"

        private val SELECT_HEADER = byteArrayOf(0x00, 0xA4.toByte(), 0x04, 0x00)
        private val OUR_AID = byteArrayOf(0xA0.toByte(), 0x00, 0x00, 0x02, 0x47, 0x10, 0x01)

        private val SW_OK        = byteArrayOf(0x90.toByte(), 0x00)
        private val SW_UNKNOWN   = byteArrayOf(0x6F.toByte(), 0x00)
        private val SW_NOT_FOUND = byteArrayOf(0x6A.toByte(), 0x82.toByte())
    }

    override fun processCommandApdu(apdu: ByteArray, extras: Bundle?): ByteArray {
        val apduHex = apdu.toHexString()
        Log.d(TAG, "NFC ДОКОСВАНЕ! Получен APDU: $apduHex")

        return when {
            isOurSelectAid(apdu) -> {
                Log.i(TAG, "✅ НАШИЯТ AID Е РАЗПОЗНАТ!")
                handleSelectAid()
            }
            else -> {
                Log.w(TAG, "❓ Непозната команда: $apduHex")
                SW_UNKNOWN
            }
        }
    }

    private fun handleSelectAid(): ByteArray {
        val prefs = StudentPrefs(this)
        val facultyNumber = prefs.facultyNumber ?: return SW_NOT_FOUND
        val hmacKeyHex = prefs.hmacKey ?: return SW_NOT_FOUND
        val atc = prefs.getAndIncrementAtc()

        val message = "$facultyNumber|$atc"

        // 1. Изчисляваме HMAC-SHA256 като СУРОВИ БАЙТОВЕ (точно 32 байта)
        val hmacRawBytes = computeHmacSha256Raw(message, hmacKeyHex)

        // 2. Текстовият хедър: "ФН|ATC|"
        val textHeaderBytes = "$facultyNumber|$atc|".toByteArray(Charsets.UTF_8)

        // 3. Сглобяваме: Текст (напр. 13 байта) + HMAC (32 байта) + Терминатор (1 байт) + SW_OK (2 байта)
        // Обща дължина: ~48 байта. Влиза перфектно под хардуерния лимит от 64!
        val responseBytes = textHeaderBytes + hmacRawBytes + byteArrayOf(0x00) + SW_OK

        Log.d(TAG, "Успешно изпратени ${responseBytes.size} байта към четеца.")
        return responseBytes
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

    /**
     * Превръща Хекс стринга от бекенда правилно в байтове за криптографския чип.
     */
    private fun computeHmacSha256Raw(message: String, keyHex: String): ByteArray {
        val keyBytes = ByteArray(keyHex.length / 2)
        for (i in keyBytes.indices) {
            val index = i * 2
            keyBytes[i] = keyHex.substring(index, index + 2).toInt(16).toByte()
        }

        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(keyBytes, "HmacSHA256"))
        return mac.doFinal(message.toByteArray(Charsets.UTF_8))
    }

    override fun onDeactivated(reason: Int) {
        Log.d(TAG, "HCE деактивиран: $reason")
    }

    private fun ByteArray.toHexString() = joinToString(" ") { "%02X".format(it) }
}
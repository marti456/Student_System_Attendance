package com.example.student_attendance_app

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/**
 * Криптирано хранилище за чувствителните данни на студента.
 * Използва Android Keystore за управление на ключовете —
 * данните не могат да се прочетат дори при root достъп.
 */
class StudentPrefs(context: Context) {

    private val masterKey = MasterKey.Builder(context)
        .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
        .build()

    private val prefs = EncryptedSharedPreferences.create(
        context,
        "student_secure_prefs",          // Файл с криптирани данни
        masterKey,
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
    )

    /** JWT токен за API заявки */
    var token: String?
        get() = prefs.getString(KEY_TOKEN, null)
        set(v) = prefs.edit().putString(KEY_TOKEN, v).apply()

    /**
     * 64-символен hex HMAC ключ (32 байта).
     * Получен от сървъра при /auth/provision-key.
     * Никога не напуска устройството след получаването.
     */
    var hmacKey: String?
        get() = prefs.getString(KEY_HMAC, null)
        set(v) = prefs.edit().putString(KEY_HMAC, v).apply()

    /** Факултетен номер — използва се в NFC payload-а */
    var facultyNumber: String?
        get() = prefs.getString(KEY_FN, null)
        set(v) = prefs.edit().putString(KEY_FN, v).apply()

    /**
     * Application Transaction Counter (ATC).
     * Монотонно нараства — никога не намалява.
     * Предотвратява replay атаки.
     */
    var atcCounter: Long
        get() = prefs.getLong(KEY_ATC, 0L)
        set(v) = prefs.edit().putLong(KEY_ATC, v).apply()

    /**
     * Атомарна операция: увеличава ATC с 1 и връща новата стойност.
     * Извиква се при всяко NFC докосване.
     */
    @Synchronized
    fun getAndIncrementAtc(): Long {
        val next = atcCounter + 1
        atcCounter = next
        return next
    }

    /** Дали студентът е провизиониран (логнат и получил HMAC ключ) */
    val isProvisioned: Boolean
        get() = hmacKey != null && facultyNumber != null

    /** Изчиства всички данни при изход */
    fun clear(context: Context) {
        prefs.edit().clear().apply()
        context.getSharedPreferences("nfc_fast_prefs", Context.MODE_PRIVATE)
            .edit().clear().apply()
    }

    companion object {
        private const val KEY_TOKEN = "token"
        private const val KEY_HMAC  = "hmac_key"
        private const val KEY_FN    = "faculty_number"
        private const val KEY_ATC   = "atc_counter"
    }
}
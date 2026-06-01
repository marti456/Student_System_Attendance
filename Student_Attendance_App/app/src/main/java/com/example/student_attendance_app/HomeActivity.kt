package com.example.student_attendance_app

import android.content.ComponentName
import android.content.Intent
import android.nfc.NfcAdapter
import android.nfc.cardemulation.CardEmulation
import android.os.Bundle
import android.util.Log
import android.widget.Button
import android.widget.TextView
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity

class HomeActivity : AppCompatActivity() {

    private lateinit var prefs: StudentPrefs
    private var nfcAdapter: NfcAdapter? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_home)

        prefs = StudentPrefs(this)
        nfcAdapter = NfcAdapter.getDefaultAdapter(this)

        val tvFacultyNumber = findViewById<TextView>(R.id.tvFacultyNumber)
        val tvNfcStatus     = findViewById<TextView>(R.id.tvNfcStatus)
        val tvAtcInfo       = findViewById<TextView>(R.id.tvAtcInfo)
        val btnLogout       = findViewById<Button>(R.id.btnLogout)

        // Показваме данните на студента
        tvFacultyNumber.text = "Факултетен №: ${prefs.facultyNumber}"
        tvAtcInfo.text       = "Брой чекирания: ${prefs.atcCounter}"

        // Проверяваме статуса на NFC
        checkNfcStatus(tvNfcStatus)

        btnLogout.setOnClickListener {
            AlertDialog.Builder(this)
                .setTitle("Изход")
                .setMessage(
                    "При следващ вход ще е нужна интернет връзка за получаване на нов NFC ключ.\n\nСигурен ли си?"
                )
                .setPositiveButton("Изход") { _, _ ->
                    prefs.clear(this)  // подаваме context
                    startActivity(Intent(this, MainActivity::class.java))
                    finish()
                }
                .setNegativeButton("Отказ", null)
                .show()
        }
    }

    override fun onResume() {
        super.onResume()
        // Обновяваме ATC брояча при всяко отваряне на екрана
        findViewById<TextView>(R.id.tvAtcInfo).text = "Брой чекирания: ${prefs.atcCounter}"

        // Форсираме системата да ползва нашия HCE сървис
        nfcAdapter?.let { adapter ->
            val hceService = ComponentName(this, NfcHceService::class.java)
            val cardEmulation = CardEmulation.getInstance(adapter)
            val result = cardEmulation.setPreferredService(this, hceService)
            Log.d("HomeActivity", "HCE Priority set: $result")
        }
    }

    override fun onPause() {
        super.onPause()
        nfcAdapter?.let { adapter ->
            CardEmulation.getInstance(adapter).unsetPreferredService(this)
        }
    }

    private fun checkNfcStatus(tvNfcStatus: TextView) {
        val nfcAdapter = NfcAdapter.getDefaultAdapter(this)

        when {
            nfcAdapter == null -> {
                tvNfcStatus.text = "❌ Устройството не поддържа NFC"
                tvNfcStatus.setTextColor(getColor(android.R.color.holo_red_dark))
            }
            !nfcAdapter.isEnabled -> {
                tvNfcStatus.text = "⚠️ NFC е изключен\nОтиди в Настройки → NFC и го включи"
                tvNfcStatus.setTextColor(getColor(android.R.color.holo_orange_dark))
            }
            else -> {
                tvNfcStatus.text = "✅ NFC е активен\nДопри телефона до четеца за чекиране"
                tvNfcStatus.setTextColor(getColor(android.R.color.holo_green_dark))
            }
        }
    }
}
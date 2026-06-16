package com.example.student_attendance_app

import android.content.ComponentName
import android.content.Intent
import android.nfc.NfcAdapter
import android.nfc.cardemulation.CardEmulation
import android.os.Bundle
import android.os.CountDownTimer
import android.util.Log
import android.view.View
import android.widget.Button
import android.widget.ImageView
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import com.bumptech.glide.Glide
import com.bumptech.glide.load.engine.DiskCacheStrategy

class HomeActivity : AppCompatActivity() {

    private lateinit var prefs: StudentPrefs
    private var nfcAdapter: NfcAdapter? = null
    private var countDownTimer: CountDownTimer? = null

    private lateinit var btnCheckin: Button
    private lateinit var tvCountdown: TextView
    private lateinit var tvNfcStatus: TextView
    private lateinit var ivStatusGif: ImageView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_home)

        prefs = StudentPrefs(this)
        nfcAdapter = NfcAdapter.getDefaultAdapter(this)

        val tvFacultyNumber = findViewById<TextView>(R.id.tvFacultyNumber)
        tvNfcStatus         = findViewById<TextView>(R.id.tvNfcStatus)
        val tvAtcInfo       = findViewById<TextView>(R.id.tvAtcInfo)
        val btnLogout       = findViewById<Button>(R.id.btnLogout)
        btnCheckin          = findViewById<Button>(R.id.btnCheckin)
        tvCountdown         = findViewById<TextView>(R.id.tvCountdown)
        ivStatusGif         = findViewById<ImageView>(R.id.ivStatusGif)

        // Изключваме хардуерното ускорение за тази картинка, за да избегнем артефакти при GIF
        ivStatusGif.setLayerType(View.LAYER_TYPE_SOFTWARE, null)

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

        btnCheckin.setOnClickListener {
            startCheckinSession()
        }
    }

    private fun startCheckinSession() {
        if (nfcAdapter?.isEnabled != true) {
            Toast.makeText(this, "Моля, включете NFC!", Toast.LENGTH_LONG).show()
            return
        }

        NfcHceService.isCheckinActive = true
        btnCheckin.isEnabled = false
        tvCountdown.visibility = View.VISIBLE
        
        loadGif(R.drawable.nfc_signal)

        countDownTimer?.cancel()
        countDownTimer = object : CountDownTimer(30000, 1000) {
            override fun onTick(millisUntilFinished: Long) {
                tvCountdown.text = "Остават: ${millisUntilFinished / 1000} сек."
                tvNfcStatus.text = "✅ NFC е активен!\nДопрете телефона до четеца."
                tvNfcStatus.setTextColor(getColor(android.R.color.holo_green_dark))
            }

            override fun onFinish() {
                // Ако таймерът изтече без успех → показваме грешка
                if (NfcHceService.isCheckinActive) {
                    showUnsuccessfulCheckin()
                }
            }
        }.start()
    }

    private fun resetCheckinUI() {
        NfcHceService.isCheckinActive = false
        btnCheckin.isEnabled = true
        tvCountdown.visibility = View.GONE
        checkNfcStatus(tvNfcStatus)
    }

    private fun showUnsuccessfulCheckin() {
        runOnUiThread {
            loadGif(R.drawable.unsuccessfull_checking)
            tvNfcStatus.text = "❌ Чекирането не бе успешно.\nОпитайте отново."
            tvNfcStatus.setTextColor(getColor(android.R.color.holo_red_dark))
            
            ivStatusGif.postDelayed({
                resetCheckinUI()
            }, 3000)
        }
    }

    override fun onResume() {
        super.onResume()
        findViewById<TextView>(R.id.tvAtcInfo).text = "Брой чекирания: ${prefs.atcCounter}"

        NfcHceService.tapCallback = {
            runOnUiThread {
                countDownTimer?.cancel()
                
                // Показваме GIF за успех
                loadGif(R.drawable.successfull_checking)
                
                // Изчакваме 3 секунди преди да върнем стандартния UI
                ivStatusGif.postDelayed({
                    resetCheckinUI()
                }, 3000)

                Toast.makeText(this, "✅ Чекирането е успешно!", Toast.LENGTH_SHORT).show()
                findViewById<TextView>(R.id.tvAtcInfo).text = "Брой чекирания: ${prefs.atcCounter}"
            }
        }

        NfcHceService.failureCallback = {
            showUnsuccessfulCheckin()
        }

        nfcAdapter?.let { adapter ->
            val hceService = ComponentName(this, NfcHceService::class.java)
            val cardEmulation = CardEmulation.getInstance(adapter)
            val result = cardEmulation.setPreferredService(this, hceService)
            Log.d("HomeActivity", "HCE Priority set: $result")
        }
    }

    override fun onPause() {
        super.onPause()
        countDownTimer?.cancel()
        NfcHceService.isCheckinActive = false
        NfcHceService.tapCallback = null
        NfcHceService.failureCallback = null

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
                loadGif(R.drawable.nfc_not_activated)
            }
            !nfcAdapter.isEnabled -> {
                tvNfcStatus.text = "⚠️ NFC е изключен\nОтиди в Настройки → NFC и го включи"
                tvNfcStatus.setTextColor(getColor(android.R.color.holo_orange_dark))
                loadGif(R.drawable.nfc_not_activated)
            }
            else -> {
                tvNfcStatus.text = "✅ NFC е активен\nНатиснете бутона за чекиране"
                tvNfcStatus.setTextColor(getColor(android.R.color.holo_green_dark))
                loadGif(R.drawable.waiting_to_start)
            }
        }
    }

    private fun loadGif(resourceId: Int) {
        // Пълно изчистване на паметта и изгледа
        Glide.with(this).clear(ivStatusGif)
        ivStatusGif.setImageDrawable(null)

        Glide.with(this)
            .load(resourceId)
            .diskCacheStrategy(DiskCacheStrategy.NONE)
            .skipMemoryCache(true)
            .into(ivStatusGif)
    }
}
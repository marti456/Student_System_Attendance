package com.example.student_attendance_app

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.launch
import retrofit2.HttpException
import java.io.IOException

class MainActivity : AppCompatActivity() {

    private lateinit var prefs: StudentPrefs

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        prefs = StudentPrefs(this)

        // Ако вече сме провизионирани → прескачаме логин екрана
        if (prefs.isProvisioned) {
            goHome()
            return
        }

        val etUsername  = findViewById<EditText>(R.id.etUsername)
        val etPassword  = findViewById<EditText>(R.id.etPassword)
        val btnLogin    = findViewById<Button>(R.id.btnLogin)
        val progressBar = findViewById<ProgressBar>(R.id.progressBar)
        val tvError     = findViewById<TextView>(R.id.tvError)

        btnLogin.setOnClickListener {
            val username = etUsername.text.toString().trim()
            val password = etPassword.text.toString()

            if (username.isEmpty() || password.isEmpty()) {
                tvError.text = "Въведете потребителско име и парола."
                tvError.visibility = View.VISIBLE
                return@setOnClickListener
            }

            tvError.visibility = View.GONE
            progressBar.visibility = View.VISIBLE
            btnLogin.isEnabled = false

            lifecycleScope.launch {
                try {
                    // Стъпка 1: Логин → вземаме JWT токен
                    val tokenResp = RetrofitClient.api.login(username, password)
                    prefs.token = tokenResp.access_token

                    // Стъпка 2: Даване на HMAC ключ
                    val keyResp = RetrofitClient.api.provisionKey("Bearer ${tokenResp.access_token}")

                    // Записваме всичко криптирано в Keystore
                    prefs.hmacKey       = keyResp.hmac_key
                    prefs.facultyNumber = keyResp.faculty_number
                    // Взимаме ATC-а от сървъра за синхронизирация при преинсталация или смяна на телефон
                    prefs.atcCounter    = keyResp.atc
                    getSharedPreferences("nfc_fast_prefs", Context.MODE_PRIVATE)
                        .edit()
                        .putString("hmac_key", keyResp.hmac_key)
                        .putString("faculty_number", keyResp.faculty_number)
                        .apply()
                    Toast.makeText(this@MainActivity, "Успешен вход!", Toast.LENGTH_SHORT).show()
                    goHome()

                } catch (e: HttpException) {
                    val msg = when (e.code()) {
                        401  -> "Грешно потребителско име или парола."
                        403  -> "Само студенти могат да използват приложението."
                        else -> "Грешка от сървъра: ${e.code()}"
                    }
                    tvError.text = msg
                    tvError.visibility = View.VISIBLE

                } catch (e: IOException) {
                    tvError.text = "Не може да се свърже със сървъра.\nПровери интернет връзката."
                    tvError.visibility = View.VISIBLE

                } catch (e: Exception) {
                    tvError.text = "Неочаквана грешка: ${e.message}"
                    tvError.visibility = View.VISIBLE

                } finally {
                    progressBar.visibility = View.GONE
                    btnLogin.isEnabled = true
                }
            }
        }
    }

    private fun goHome() {
        startActivity(Intent(this, HomeActivity::class.java))
        finish()  // Затваряме Login activity — бутон "Назад" не се връща тук
    }
}
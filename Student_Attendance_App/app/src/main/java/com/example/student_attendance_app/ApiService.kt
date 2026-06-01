package com.example.student_attendance_app

import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import retrofit2.http.*

// ─── Data класове ───────────────────────────────────────────

data class TokenResponse(
    val access_token: String,
    val token_type: String
)

data class ProvisionKeyResponse(
    val hmac_key: String,
    val faculty_number: String,
    val atc: Long           // BigInteger от сървъра → Long в Kotlin
)

data class MessageResponse(
    val detail: String
)

// ─── Retrofit интерфейс ──────────────────────────────────────

interface ApiService {

    /**
     * Логин — OAuth2 форма (application/x-www-form-urlencoded).
     * Бекендът използва FastAPI OAuth2PasswordRequestForm.
     */
    @FormUrlEncoded
    @POST("auth/login")
    suspend fun login(
        @Field("username") username: String,
        @Field("password") password: String
    ): TokenResponse

    /**
     * Провизиониране на HMAC ключ.
     * Извиква се веднъж след логин — връща ключа и текущия ATC.
     */
    @POST("auth/provision-key")
    suspend fun provisionKey(
        @Header("Authorization") bearerToken: String
    ): ProvisionKeyResponse
}

// ─── Singleton клиент ────────────────────────────────────────

object RetrofitClient {

    /**
     * Смени с реалния IP/домейн на сървъра.
     * В продукция използвай https://!
     */
    private const val BASE_URL = "http://192.168.1.150:8000/"

    val api: ApiService by lazy {
        Retrofit.Builder()
            .baseUrl(BASE_URL)
            .addConverterFactory(GsonConverterFactory.create())
            .build()
            .create(ApiService::class.java)
    }
}
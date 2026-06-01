# Add project specific ProGuard rules here.

# Retrofit
-keepattributes Signature, InnerClasses, EnclosingMethod
-keepattributes RuntimeVisibleAnnotations, RuntimeVisibleParameterAnnotations
-keepattributes AnnotationDefault
-dontwarn retrofit2.**
-keep class retrofit2.** { *; }
-keepclasseswithmembers interface * {
    @retrofit2.http.* <methods>;
}

# Gson
-keepattributes Signature
-keepattributes *Annotation*
-dontwarn sun.misc.**
-keep class com.google.gson.** { *; }

# Keep our data classes from being obfuscated as they are used for JSON serialization
-keep class com.example.student_attendance_app.TokenResponse { *; }
-keep class com.example.student_attendance_app.ProvisionKeyResponse { *; }
-keep class com.example.student_attendance_app.MessageResponse { *; }

# Alternatively, keep all classes in the package if it contains only data models
# -keep class com.example.student_attendance_app.** { *; }

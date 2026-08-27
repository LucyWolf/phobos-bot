package com.phobosbot.androidhost

import android.content.ContentValues
import android.content.Intent
import android.net.wifi.WifiManager
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.os.Handler
import android.os.Looper
import android.provider.MediaStore
import android.text.format.Formatter
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import java.io.File
import java.net.InetSocketAddress
import java.net.Socket
import kotlin.concurrent.thread

class MainActivity : AppCompatActivity() {

    private val notificationPermissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { /* ignored:
            the service still runs without it, just without a visible notification on API 33+ */
        }

    private val storagePermissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            if (granted) {
                saveCrashLogToDownloads()
            } else {
                val pathView = findViewById<TextView>(R.id.saveLogPathText)
                pathView.text = "Speichern fehlgeschlagen - Berechtigung verweigert"
                pathView.visibility = View.VISIBLE
            }
        }

    private val statusHandler = Handler(Looper.getMainLooper())
    private var statusCheckRunnable: Runnable? = null
    private var crashLogLoaded = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        val statusText = findViewById<TextView>(R.id.statusText)
        val startButton = findViewById<Button>(R.id.startButton)
        val stopButton = findViewById<Button>(R.id.stopButton)

        statusText.text = "Dashboard will be reachable at:\nhttp://${getLocalIpAddress()}:8080"

        startButton.setOnClickListener {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                notificationPermissionLauncher.launch(android.Manifest.permission.POST_NOTIFICATIONS)
            }
            val intent = Intent(this, PhobosService::class.java)
            ContextCompat.startForegroundService(this, intent)
        }

        stopButton.setOnClickListener {
            stopService(Intent(this, PhobosService::class.java))
        }

        findViewById<Button>(R.id.saveLogButton).setOnClickListener {
            // getExternalFilesDir(null) (Android/data/.../files/) is invisible to USB/MTP file
            // browsers and on-device file managers since Android 11 - scoped storage hides it
            // regardless of what the app writes there. The public Downloads folder stays
            // visible on every version, but needs two different write paths: MediaStore on
            // API 29+ (no permission needed), a direct File write + a runtime permission below.
            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q &&
                ContextCompat.checkSelfPermission(
                    this, android.Manifest.permission.WRITE_EXTERNAL_STORAGE
                ) != android.content.pm.PackageManager.PERMISSION_GRANTED
            ) {
                storagePermissionLauncher.launch(android.Manifest.permission.WRITE_EXTERNAL_STORAGE)
            } else {
                saveCrashLogToDownloads()
            }
        }
    }

    private fun saveCrashLogToDownloads() {
        val text = findViewById<EditText>(R.id.crashLogText).text.toString()
        val pathView = findViewById<TextView>(R.id.saveLogPathText)
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                val values = ContentValues().apply {
                    put(MediaStore.MediaColumns.DISPLAY_NAME, "phobos-crash.txt")
                    put(MediaStore.MediaColumns.MIME_TYPE, "text/plain")
                }
                val uri = contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
                    ?: throw Exception("MediaStore.insert() gab null zurück")
                contentResolver.openOutputStream(uri)?.use { it.write(text.toByteArray()) }
                    ?: throw Exception("openOutputStream() gab null zurück")
                pathView.text = "Gespeichert: Downloads/phobos-crash.txt\n(per USB am PC im Downloads-Ordner zu finden)"
            } else {
                val dir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
                dir.mkdirs()
                val file = File(dir, "phobos-crash.txt")
                file.writeText(text)
                pathView.text = "Gespeichert: ${file.absolutePath}\n(per USB am PC im Downloads-Ordner zu finden)"
            }
            pathView.visibility = View.VISIBLE
            Toast.makeText(this, "Gespeichert", Toast.LENGTH_SHORT).show()
        } catch (e: Exception) {
            pathView.text = "Speichern fehlgeschlagen: ${e.message}"
            pathView.visibility = View.VISIBLE
        }
    }

    override fun onResume() {
        super.onResume()
        startStatusChecks()
    }

    override fun onPause() {
        super.onPause()
        statusCheckRunnable?.let { statusHandler.removeCallbacks(it) }
    }

    private fun startStatusChecks() {
        val runnable = object : Runnable {
            override fun run() {
                checkServerStatus()
                statusHandler.postDelayed(this, 2000)
            }
        }
        statusCheckRunnable = runnable
        statusHandler.post(runnable)
    }

    private fun checkServerStatus() {
        thread(name = "phobos-status-check") {
            // A plain TCP connect to the dashboard's own port, from the phone to itself - not a
            // real HTTP request, just checks whether something is listening there at all. This
            // is what actually distinguishes the two possible failure modes: if this never
            // succeeds, the bot process itself never came up (crashed/still starting); if it
            // succeeds here but other devices still can't reach <phone-ip>:8080, the bot is
            // fine and it's a network/firewall problem instead.
            val reachable = try {
                Socket().use { socket ->
                    socket.connect(InetSocketAddress("127.0.0.1", 8080), 800)
                    true
                }
            } catch (e: Exception) {
                false
            }
            // PhobosService writes these to filesDir so the actual crash reason can be shown
            // directly in the app - there's no adb access to this test device to read logcat.
            val crashLog = File(filesDir, "crash.log")
            val startAttempted = File(filesDir, "start_attempted.log").exists()

            runOnUiThread {
                val statusView = findViewById<TextView>(R.id.serverStatusText)
                val crashView = findViewById<EditText>(R.id.crashLogText)
                val saveButton = findViewById<Button>(R.id.saveLogButton)
                statusView.text = when {
                    reachable -> "✅ Bot läuft (Port 8080 lokal erreichbar)"
                    !startAttempted -> "⏳ Noch nicht gestartet - auf \"Start Bot\" tippen"
                    crashLog.exists() -> "❌ Abgestürzt - Fehler unten"
                    else -> "⏳ Startet noch… (oder hängt fest, falls das lange so bleibt)"
                }
                if (crashLog.exists()) {
                    // Only populate once - this runs every 2s, and overwriting the EditText's
                    // content while the user is scrolling/selecting text in it would be annoying.
                    // The crash log itself is a static snapshot anyway, it won't change on its own.
                    if (!crashLogLoaded) {
                        crashView.setText(crashLog.readText())
                        crashLogLoaded = true
                    }
                    crashView.visibility = View.VISIBLE
                    saveButton.visibility = View.VISIBLE
                } else {
                    crashView.visibility = View.GONE
                    saveButton.visibility = View.GONE
                    crashLogLoaded = false
                }
            }
        }
    }

    private fun getLocalIpAddress(): String {
        val wifiManager = applicationContext.getSystemService(WIFI_SERVICE) as WifiManager
        @Suppress("DEPRECATION")
        val ipInt = wifiManager.connectionInfo.ipAddress
        return if (ipInt != 0) Formatter.formatIpAddress(ipInt) else "<check Wi-Fi settings>"
    }
}

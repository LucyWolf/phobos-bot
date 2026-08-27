package com.phobosbot.androidhost

import android.content.Intent
import android.net.wifi.WifiManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.format.Formatter
import android.widget.Button
import android.widget.TextView
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import java.net.InetSocketAddress
import java.net.Socket
import kotlin.concurrent.thread

class MainActivity : AppCompatActivity() {

    private val notificationPermissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { /* ignored:
            the service still runs without it, just without a visible notification on API 33+ */
        }

    private val statusHandler = Handler(Looper.getMainLooper())
    private var statusCheckRunnable: Runnable? = null

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
            runOnUiThread {
                val statusView = findViewById<TextView>(R.id.serverStatusText)
                statusView.text = if (reachable) {
                    "✅ Bot läuft (Port 8080 lokal erreichbar)"
                } else {
                    "⏳ Nicht erreichbar - noch nicht gestartet, gestoppt, oder abgestürzt"
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

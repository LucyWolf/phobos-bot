package com.phobosbot.androidhost

import android.content.Intent
import android.net.wifi.WifiManager
import android.os.Build
import android.os.Bundle
import android.text.format.Formatter
import android.widget.Button
import android.widget.TextView
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat

class MainActivity : AppCompatActivity() {

    private val notificationPermissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { /* ignored:
            the service still runs without it, just without a visible notification on API 33+ */
        }

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

    private fun getLocalIpAddress(): String {
        val wifiManager = applicationContext.getSystemService(WIFI_SERVICE) as WifiManager
        @Suppress("DEPRECATION")
        val ipInt = wifiManager.connectionInfo.ipAddress
        return if (ipInt != 0) Formatter.formatIpAddress(ipInt) else "<check Wi-Fi settings>"
    }
}

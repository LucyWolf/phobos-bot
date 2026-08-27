package com.phobosbot.androidhost

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import android.system.Os
import androidx.core.app.NotificationCompat
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import java.io.File
import kotlin.concurrent.thread

/**
 * Foreground service that hosts the whole bot process (Discord connection + FastAPI dashboard)
 * inside this Android app, reusing the exact same main.py the Docker/Termux deployments run.
 *
 * NOT verified against a real device/emulator - see android/README.md for the untested
 * assumptions this makes (chiefly: whether every dependency in requirements.txt actually
 * builds for Android under Chaquopy, and whether "dataSync" is accepted as this service's
 * foreground-service type on real hardware).
 */
class PhobosService : Service() {

    companion object {
        private const val CHANNEL_ID = "phobos_bot_service"
        private const val NOTIFICATION_ID = 1
    }

    private var wakeLock: PowerManager.WakeLock? = null
    private var started = false

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
        startForeground(NOTIFICATION_ID, buildNotification())

        // main.py serves forever (asyncio.run(main()) never returns under normal operation) -
        // without a wake lock, Android can suspend the CPU and stall the event loop while the
        // screen is off, even though the process itself keeps running.
        val pm = getSystemService(POWER_SERVICE) as PowerManager
        wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "PhobosBot::ServiceWakeLock")
        wakeLock?.acquire()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (!started) {
            started = true
            startPython()
        }
        // START_STICKY: ask Android to restart this service if it gets killed under memory
        // pressure - the bot itself already handles a fresh start cleanly (init_db() etc. are
        // idempotent), so this is a reasonable default for "keep this alive as long as possible".
        return START_STICKY
    }

    private fun startPython() {
        // PHOBOS_DATA_DIR/PHOBOS_DB_PATH are the same env vars added for Termux support -
        // pointing them at this app's private storage directory reuses that mechanism as-is,
        // no Android-specific change was needed in the Python code itself for this part.
        val dataDir = filesDir.absolutePath
        Os.setenv("PHOBOS_DATA_DIR", dataDir, true)
        Os.setenv("PHOBOS_DB_PATH", "$dataDir/phobos.db", true)
        // Lets main.py tell this build apart from Termux (which sets the same two vars above) -
        // only Android needs the APK-download update flow instead of the git-based one.
        Os.setenv("PHOBOS_PLATFORM", "android", true)

        if (!Python.isStarted()) {
            Python.start(AndroidPlatform(applicationContext))
        }

        // Marker written before even attempting to start - lets MainActivity tell "crashed and
        // wrote a crash log" apart from "never got this far / still hanging with no log yet".
        File(filesDir, "crash.log").delete()
        File(filesDir, "start_attempted.log").writeText(java.util.Date().toString())

        // Runs on a background thread, not the service's own binder thread - main.py's
        // asyncio.run(main()) blocks forever serving the bot + dashboard, which would hang/ANR
        // if called directly on onStartCommand's calling thread.
        thread(name = "phobos-python") {
            try {
                // Importing the module is enough to trigger its top-level `asyncio.run(main())` -
                // main.py has no `if __name__ == "__main__":` guard, matching how it's always
                // been invoked (`python main.py` under Docker/Termux too).
                Python.getInstance().getModule("main")
            } catch (e: Exception) {
                // Without adb access to the test device, logcat alone isn't reachable - write the
                // full exception to a file MainActivity can read and display directly in the UI.
                android.util.Log.e("PhobosService", "Bot process ended/crashed", e)
                try {
                    File(filesDir, "crash.log").writeText(
                        "Crashed at ${java.util.Date()}\n\n${android.util.Log.getStackTraceString(e)}"
                    )
                } catch (writeError: Exception) {
                    android.util.Log.e("PhobosService", "Couldn't even write crash.log", writeError)
                }
            }
        }
    }

    override fun onDestroy() {
        wakeLock?.let { if (it.isHeld) it.release() }
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID, "Phobos Bot", NotificationManager.IMPORTANCE_LOW
            )
            channel.description = "Keeps the Discord bot and dashboard running"
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(channel)
        }
    }

    private fun buildNotification(): Notification {
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("Phobos Bot")
            .setContentText("Running - dashboard reachable on port 8080")
            .setSmallIcon(android.R.drawable.ic_menu_manage)
            .setOngoing(true)
            .build()
    }
}

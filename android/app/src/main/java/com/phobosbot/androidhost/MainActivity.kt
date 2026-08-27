package com.phobosbot.androidhost

import android.content.ContentValues
import android.content.Intent
import android.net.Uri
import android.net.wifi.WifiManager
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.os.Handler
import android.os.Looper
import android.media.MediaScannerConnection
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
import androidx.core.content.FileProvider
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
    private var loadedLogFile: String? = null
    private var activeLogFilename = "phobos-crash.txt"
    private var updateInstallTriggered = false

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
                    put(MediaStore.MediaColumns.DISPLAY_NAME, activeLogFilename)
                    put(MediaStore.MediaColumns.MIME_TYPE, "text/plain")
                }
                val uri = contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
                    ?: throw Exception("MediaStore.insert() gab null zurück")
                contentResolver.openOutputStream(uri)?.use { it.write(text.toByteArray()) }
                    ?: throw Exception("openOutputStream() gab null zurück")
                pathView.text = "Gespeichert: Downloads/$activeLogFilename\n(per USB am PC im Downloads-Ordner zu finden)"
            } else {
                val dir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
                dir.mkdirs()
                val file = File(dir, activeLogFilename)
                file.writeText(text)
                // A direct File write like this doesn't touch the MediaStore index that USB/MTP
                // relies on to show files to a connected PC - without an explicit scan, the file
                // sits on disk (visible to on-device file managers) but stays invisible over USB
                // until Android happens to index it on its own, which can take a long time.
                MediaScannerConnection.scanFile(this, arrayOf(file.absolutePath), null, null)
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
            // PhobosService writes crash.log if the whole process dies; main.py's own global
            // FastAPI exception handler writes web_errors.log for exceptions inside a single
            // request, which DON'T kill the process (so crash.log alone would miss them - the
            // dashboard just shows a plain "Internal Server Error" with nothing else to go on
            // otherwise). Either way there's no adb access to this test device to read logcat.
            val crashLog = File(filesDir, "crash.log")
            val webErrorsLog = File(filesDir, "web_errors.log")
            val updateDebugLog = File(filesDir, "update_debug.log")
            val startAttempted = File(filesDir, "start_attempted.log").exists()
            // crash.log wins when both exist - a dead process is the more urgent problem.
            // update_debug.log is lowest priority - a rare diagnostic, not something that
            // should hide a live crash/request error if one is also present.
            val shownLog = when {
                crashLog.exists() -> crashLog
                webErrorsLog.exists() -> webErrorsLog
                updateDebugLog.exists() -> updateDebugLog
                else -> null
            }
            // Written by main.py's Android update flow once the new APK is fully downloaded
            // (renamed into place only after a complete write - see _do_android_update in
            // main.py) - triggered from the dashboard's Update page, on ANY device on the
            // network, but the actual download+install happens locally on this phone.
            val updateApk = File(filesDir, "update.apk")
            // Launching the system installer backgrounds/pauses MainActivity, and on this old
            // device Android sometimes actually destroys the Activity instance while it's not
            // in front (rather than just pausing it) - the in-memory updateInstallTriggered flag
            // resets on that recreation, so the dialog kept reappearing every time the user came
            // back to the app ("wieder dann wieder dann wieder"). A real file survives that,
            // an in-memory field doesn't. Comparing mtimes (not just existence) still lets a
            // genuinely NEWER update.apk from a future update trigger a fresh install prompt.
            val triggerMarker = File(filesDir, "update_install_triggered.marker")
            val shouldTriggerInstall = updateApk.exists() &&
                (!triggerMarker.exists() || triggerMarker.lastModified() < updateApk.lastModified())

            runOnUiThread {
                if (shouldTriggerInstall && !updateInstallTriggered) {
                    updateInstallTriggered = true
                    triggerMarker.writeText(java.util.Date().toString())
                    triggerApkInstall(updateApk)
                }
                val statusView = findViewById<TextView>(R.id.serverStatusText)
                val logView = findViewById<EditText>(R.id.crashLogText)
                val saveButton = findViewById<Button>(R.id.saveLogButton)
                statusView.text = when {
                    reachable && webErrorsLog.exists() -> "✅ Bot läuft (Port 8080 erreichbar) - aber mindestens ein Anfrage-Fehler unten"
                    reachable -> "✅ Bot läuft (Port 8080 lokal erreichbar)"
                    !startAttempted -> "⏳ Noch nicht gestartet - auf \"Start Bot\" tippen"
                    crashLog.exists() -> "❌ Abgestürzt - Fehler unten"
                    else -> "⏳ Startet noch… (oder hängt fest, falls das lange so bleibt)"
                }
                if (shownLog != null) {
                    // Only populate once per file - this runs every 2s, and overwriting the
                    // EditText's content while the user is scrolling/selecting text in it would
                    // be annoying. Re-populate if which file is being shown actually changes
                    // (e.g. a request error appears while already looking at an old one).
                    if (loadedLogFile != shownLog.name) {
                        logView.setText(shownLog.readText())
                        loadedLogFile = shownLog.name
                        activeLogFilename = when (shownLog.name) {
                            "crash.log" -> "phobos-crash.txt"
                            "web_errors.log" -> "phobos-web-errors.txt"
                            else -> "phobos-update-debug.txt"
                        }
                    }
                    logView.visibility = View.VISIBLE
                    saveButton.visibility = View.VISIBLE
                } else {
                    logView.visibility = View.GONE
                    saveButton.visibility = View.GONE
                    loadedLogFile = null
                }
            }
        }
    }

    private fun triggerApkInstall(apkFile: File) {
        // Writes every step to a file instead of relying on the user having noticed a Toast -
        // the first attempt at this (v1.6.42) produced no visible effect at all and no dialog,
        // with no way to tell from a Toast alone whether the Intent even fired, so this time
        // there's an actual record to look at instead of guessing again.
        val debugLog = File(filesDir, "update_debug.log")
        fun dlog(msg: String) {
            try {
                debugLog.appendText("${java.util.Date()}  $msg\n")
            } catch (e: Exception) { /* nothing more to do if even this fails */ }
        }
        try {
            dlog("triggerApkInstall() called, apk=${apkFile.absolutePath} size=${apkFile.length()}, SDK_INT=${Build.VERSION.SDK_INT}")
            // v1.6.44's content:// attempt (via FileProvider) genuinely had 0 activities able to
            // handle it - confirmed for real this time by ActivityNotFoundException, not just
            // queryIntentActivities()'s earlier false negative. On this API 23 device, the
            // installer apparently only registers for file:// URIs, not content:// - which is
            // actually fine to use here: the file:// StrictMode restriction that content:// URIs
            // exist to work around wasn't introduced until API 24, so a plain file:// Uri is
            // still completely normal and unblocked on anything below that.
            val intent = Intent(Intent.ACTION_VIEW).apply {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
                    val uri = FileProvider.getUriForFile(this@MainActivity, "com.phobosbot.androidhost.fileprovider", apkFile)
                    dlog("API >= 24: using FileProvider content:// URI: $uri")
                    setDataAndType(uri, "application/vnd.android.package-archive")
                    addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                } else {
                    // filesDir (internal storage) is sandboxed per-app at the Linux permission
                    // level - the installer process can't read it via a raw file:// path no
                    // matter the Android version, that's not what the API-24 content:// change
                    // was even about. getExternalFilesDir() lives on the shared storage
                    // partition instead - no runtime permission needed to write there on any
                    // API level, and readable by other apps (like the installer) the way
                    // anything under /storage/emulated/0/... normally is.
                    val extDir = getExternalFilesDir(null)
                        ?: throw Exception("Kein externer Speicher verfügbar für die Installationskopie")
                    val extApk = File(extDir, "update.apk")
                    apkFile.copyTo(extApk, overwrite = true)
                    dlog("API < 24: copied to external storage: ${extApk.absolutePath}")
                    val uri = Uri.fromFile(extApk)
                    dlog("API < 24: using plain file:// URI: $uri")
                    setDataAndType(uri, "application/vnd.android.package-archive")
                }
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            startActivity(intent)
            dlog("startActivity() returned without throwing.")
        } catch (e: Exception) {
            dlog("EXCEPTION: ${e.javaClass.simpleName}: ${e.message}\n${android.util.Log.getStackTraceString(e)}")
            Toast.makeText(this, "Installation konnte nicht gestartet werden: ${e.message}", Toast.LENGTH_LONG).show()
        }
    }

    private fun getLocalIpAddress(): String {
        val wifiManager = applicationContext.getSystemService(WIFI_SERVICE) as WifiManager
        @Suppress("DEPRECATION")
        val ipInt = wifiManager.connectionInfo.ipAddress
        return if (ipInt != 0) Formatter.formatIpAddress(ipInt) else "<check Wi-Fi settings>"
    }
}

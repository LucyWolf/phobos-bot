package com.phobosbot.androidhost

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import androidx.core.content.ContextCompat

/** Restarts the bot service after a phone reboot - the Termux setup needs Termux:Boot for the
 * same thing, this is the equivalent for a packaged app. Requires the phone to actually be
 * unlocked at least once after boot before BOOT_COMPLETED fires (standard Android behavior on
 * encrypted storage, not something specific to this app). */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_BOOT_COMPLETED) {
            ContextCompat.startForegroundService(context, Intent(context, PhobosService::class.java))
        }
    }
}

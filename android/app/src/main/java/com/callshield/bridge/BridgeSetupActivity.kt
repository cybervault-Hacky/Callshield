package com.callshield.bridge

import android.app.Activity
import android.os.Bundle
import android.widget.TextView

/**
 * Minimal placeholder activity — no UI, just for system requirements.
 * Real configuration is via Termux: callshield screening status
 */
class BridgeSetupActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val tv = TextView(this)
        tv.text = "CallShield Bridge\n\nThis app has no UI.\nUse Termux: callshield screening status\n\nPhase 4 dry-run: does not reject calls."
        tv.textSize = 16f
        tv.setPadding(32, 32, 32, 32)
        setContentView(tv)
    }
}

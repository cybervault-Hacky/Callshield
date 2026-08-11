package com.callshield.bridge

import android.app.Activity
import android.app.role.RoleManager
import android.os.Bundle

/** Minimal role-request activity; CALLSHIELD configuration remains in Termux. */
class BridgeSetupActivity : Activity() {
    companion object {
        private const val ROLE_REQUEST_CODE = 40
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val roleManager = getSystemService(RoleManager::class.java)
        if (
            roleManager != null &&
            roleManager.isRoleAvailable(RoleManager.ROLE_CALL_SCREENING) &&
            !roleManager.isRoleHeld(RoleManager.ROLE_CALL_SCREENING)
        ) {
            startActivityForResult(
                roleManager.createRequestRoleIntent(RoleManager.ROLE_CALL_SCREENING),
                ROLE_REQUEST_CODE
            )
        } else {
            finish()
        }
    }

    @Suppress("DEPRECATION")
    override fun onActivityResult(
        requestCode: Int,
        resultCode: Int,
        data: android.content.Intent?
    ) {
        super.onActivityResult(requestCode, resultCode, data)
        finish()
    }
}

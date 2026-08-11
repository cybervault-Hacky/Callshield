package com.callshield.bridge

import android.telecom.Call
import android.telecom.CallScreeningService
import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull

/**
 * Minimal CallScreeningService for CALLSHIELD Phase 4.
 * - Receives real incoming call screening requests from Android
 * - Extracts number, validates, sends to Termux daemon via BridgeClient
 * - Waits with strict timeout (1500ms default)
 * - Logs decision, returns DRY-RUN response (always ALLOW)
 * - Never rejects calls in Phase 4, never blocks indefinitely, never uses shell/root
 */
class CallShieldScreeningService : CallScreeningService() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val bridgeClient = BridgeClient()
    private val TAG = "CallShieldScreening"

    override fun onScreenCall(callDetails: Call.Details) {
        val isIncoming = callDetails.callDirection == Call.Details.DIRECTION_INCOMING
        if (!isIncoming) {
            Log.d(TAG, "Not incoming, allowing")
            respondToCall(callDetails, CallResponse.Builder().build())
            return
        }

        val rawNumber = callDetails.handle?.schemeSpecificPart ?: ""
        if (rawNumber.isBlank()) {
            Log.w(TAG, "No number, allowing")
            respondToCall(callDetails, CallResponse.Builder().build())
            return
        }

        // Normalize loosely: keep + and digits, strip spaces/dashes
        val number = normalizeNumber(rawNumber)
        Log.i(TAG, "Screening incoming call: ${maskNumber(number)}")

        scope.launch {
            val result = withTimeoutOrNull(1600) {
                // Use screening timeout from config (default 1500ms) is enforced inside BridgeClient
                bridgeClient.screenNumber(number)
            } ?: ScreeningResult.unknown(java.util.UUID.randomUUID().toString(), "SCREENING_TIMEOUT")

            // Log screening event
            Log.i(TAG, "Screening result for ${maskNumber(number)}: risk=${result.riskScore} verdict=${result.verdict} rec=${result.recommendedAction} applied=${result.appliedAction} mode=${result.mode} reason=${result.reason}")

            // Phase 4 DRY-RUN: always ALLOW, never reject
            // We explicitly do NOT call setDisallowCall(true) / setRejectCall(true) / setSilenceCall(true)
            val response = CallResponse.Builder()
                .setDisallowCall(false)
                .setRejectCall(false)
                .setSkipCallLog(false)
                .setSkipNotification(false)
                .build()

            // Record that recommended was BLOCK but applied ALLOW in dry-run
            if (result.recommendedAction == "BLOCK") {
                Log.i(TAG, "Dry-run: recommended BLOCK but applied ALLOW for ${maskNumber(number)}")
            }

            try {
                respondToCall(callDetails, response)
            } catch (e: Exception) {
                Log.e(TAG, "Failed to respond to call", e)
            }
        }
    }

    private fun normalizeNumber(raw: String): String {
        // Keep + and digits, remove common formatting
        var cleaned = raw.replace(Regex("[\\s\\-\\.\\(\\)\\[\\]/\\\\]+"), "")
        if (cleaned.startsWith("00")) cleaned = "+" + cleaned.substring(2)
        // Validate allowed chars
        if (!cleaned.matches(Regex("^\\+?[0-9]+$"))) {
            // If contains letters, treat as invalid
            return raw
        }
        if (!cleaned.startsWith("+")) cleaned = "+$cleaned"
        return cleaned
    }

    private fun maskNumber(number: String): String {
        if (number.length <= 4) return "***"
        val digits = number.filter { it.isDigit() }
        if (digits.length <= 4) return "***"
        val prefix = if (number.startsWith("+")) "+" else ""
        val keep = minOf(3, digits.length - 4 - 2)
        val suffix = digits.takeLast(4)
        val middle = "*".repeat(maxOf(2, digits.length - keep - 4))
        return prefix + digits.take(keep) + middle + suffix
    }
}

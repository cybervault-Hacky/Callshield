package com.callshield.bridge

import android.telecom.Call
import android.telecom.CallScreeningService
import android.telecom.PhoneAccount
import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull

/** Android call-screening entry point. Phase 4 is strictly advisory. */
class CallShieldScreeningService : CallScreeningService() {
    companion object {
        private const val TAG = "CallShieldScreening"
        private const val SERVICE_TIMEOUT_MS = 1500L
    }

    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val bridgeClient = BridgeClient(timeoutMs = SERVICE_TIMEOUT_MS.toInt())

    override fun onScreenCall(callDetails: Call.Details) {
        if (callDetails.callDirection != Call.Details.DIRECTION_INCOMING) {
            respondAllow(callDetails, ScreeningResult.unknown("OUTGOING_CALL"))
            return
        }

        val handle = callDetails.handle
        if (handle == null || !handle.scheme.equals(PhoneAccount.SCHEME_TEL, ignoreCase = true)) {
            respondAllow(callDetails, ScreeningResult.unknown("INVALID_HANDLE"))
            return
        }
        val number = Protocol.normalizeTelNumber(handle.schemeSpecificPart)
        if (number == null) {
            respondAllow(callDetails, ScreeningResult.unknown("INVALID_NUMBER"))
            return
        }

        serviceScope.launch {
            var result = ScreeningResult.unknown("INTERNAL_ERROR")
            try {
                result = withTimeoutOrNull(SERVICE_TIMEOUT_MS) {
                    bridgeClient.screenNumber(number)
                } ?: ScreeningResult.unknown("SCREENING_TIMEOUT", SERVICE_TIMEOUT_MS.toInt())
            } catch (exception: Exception) {
                Log.w(TAG, "Bridge failure: ${exception.javaClass.simpleName}")
                result = ScreeningResult.unknown("INTERNAL_ERROR")
            } finally {
                Log.i(
                    TAG,
                    "number=${maskNumber(number)} verdict=${result.verdict} " +
                        "recommended=${result.recommendedAction} applied=${result.appliedAction} " +
                        "mode=${result.mode} reason=${result.reason} latency=${result.latencyMs}ms"
                )
                respondAllow(callDetails, result)
            }
        }
    }

    private fun respondAllow(callDetails: Call.Details, result: ScreeningResult) {
        val response = CallResponse.Builder()
            .setDisallowCall(false)
            .setRejectCall(false)
            .setSkipCallLog(false)
            .setSkipNotification(false)
            .build()
        try {
            respondToCall(callDetails, response)
        } catch (exception: Exception) {
            Log.w(
                TAG,
                "Unable to deliver ALLOW response (${result.reason}): " +
                    exception.javaClass.simpleName
            )
        }
    }

    private fun maskNumber(number: String): String {
        val digits = number.filter(Char::isDigit)
        if (digits.length <= 4) return "****"
        val prefix = if (number.startsWith("+")) "+" else ""
        return prefix + "*".repeat(digits.length - 4) + digits.takeLast(4)
    }
}

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

/** Android call-screening entry point with fail-open Phase 5 ACTIVE support. */
class CallShieldScreeningService : CallScreeningService() {
    companion object {
        private const val TAG = "CallShieldScreening"
        private const val SERVICE_TIMEOUT_MS = 1500L
    }

    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val bridgeClient = BridgeClient(timeoutMs = SERVICE_TIMEOUT_MS.toInt())

    override fun onScreenCall(callDetails: Call.Details) {
        if (callDetails.callDirection != Call.Details.DIRECTION_INCOMING) {
            respondWithDecision(callDetails, ScreeningResult.unknown("OUTGOING_CALL"))
            return
        }

        val handle = callDetails.handle
        if (handle == null || !handle.scheme.equals(PhoneAccount.SCHEME_TEL, ignoreCase = true)) {
            respondWithDecision(callDetails, ScreeningResult.unknown("INVALID_HANDLE"))
            return
        }
        val number = Protocol.normalizeTelNumber(handle.schemeSpecificPart)
        if (number == null) {
            respondWithDecision(callDetails, ScreeningResult.unknown("INVALID_NUMBER"))
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
                val delivered = respondWithDecision(callDetails, result)
                if (delivered && result.shouldApplyBlock()) {
                    bridgeClient.confirmRejection(result.requestId)
                }
            }
        }
    }

    private fun respondWithDecision(
        callDetails: Call.Details,
        result: ScreeningResult
    ): Boolean {
        val reject = result.shouldApplyBlock()
        val response = CallResponse.Builder()
            .setDisallowCall(reject)
            .setRejectCall(reject)
            .setSkipCallLog(false)
            .setSkipNotification(false)
            .build()
        return try {
            respondToCall(callDetails, response)
            true
        } catch (exception: Exception) {
            Log.w(
                TAG,
                "Unable to deliver fail-open response (${result.reason}): " +
                    exception.javaClass.simpleName
            )
            false
        }
    }

    private fun maskNumber(number: String): String {
        val digits = number.filter(Char::isDigit)
        if (digits.length <= 4) return "****"
        val prefix = if (number.startsWith("+")) "+" else ""
        return prefix + "*".repeat(digits.length - 4) + digits.takeLast(4)
    }
}

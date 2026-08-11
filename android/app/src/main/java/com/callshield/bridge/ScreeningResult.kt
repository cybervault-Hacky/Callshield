package com.callshield.bridge

/** Validated screening decision consumed by CallShieldScreeningService. */
data class ScreeningResult(
    val requestId: String,
    val riskScore: Int,
    val confidence: Int,
    val verdict: String,
    val recommendedAction: String,
    val appliedAction: String,
    val mode: String,
    val reason: String,
    val latencyMs: Int,
    val policyName: String,
    val emergencyOff: Boolean
) {
    /** Android permits rejection only for the exact ACTIVE + BLOCK pair. */
    fun shouldApplyBlock(): Boolean {
        return appliedAction == "BLOCK" &&
            mode == "ACTIVE" &&
            recommendedAction == "BLOCK" &&
            !emergencyOff
    }

    companion object {
        fun fromProtocolResponse(response: Protocol.ScreeningResponse): ScreeningResult {
            val applyBlock = response.appliedAction == "BLOCK" &&
                response.mode == "ACTIVE" &&
                response.recommendedAction == "BLOCK" &&
                !response.emergencyOff &&
                !response.policyError
            return ScreeningResult(
                requestId = response.requestId,
                riskScore = response.riskScore.coerceIn(0, 100),
                confidence = response.confidence.coerceIn(0, 100),
                verdict = response.verdict,
                recommendedAction = response.recommendedAction,
                appliedAction = if (applyBlock) "BLOCK" else "ALLOW",
                mode = if (applyBlock) "ACTIVE" else response.mode,
                reason = response.reason,
                latencyMs = response.latencyMs.coerceAtLeast(0),
                policyName = response.policyName,
                emergencyOff = response.emergencyOff
            )
        }

        fun unknown(reason: String, latencyMs: Int = 0): ScreeningResult {
            return ScreeningResult(
                requestId = java.util.UUID.randomUUID().toString(),
                riskScore = 0,
                confidence = 0,
                verdict = "UNKNOWN",
                recommendedAction = "ALLOW",
                appliedAction = "ALLOW",
                mode = "DRY_RUN",
                reason = reason,
                latencyMs = latencyMs.coerceAtLeast(0),
                policyName = "BALANCED",
                emergencyOff = true
            )
        }
    }
}

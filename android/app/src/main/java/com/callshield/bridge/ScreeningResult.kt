package com.callshield.bridge

/**
 * Result of a screening decision.
 * Phase 4: appliedAction is always ALLOW (dry-run).
 */
data class ScreeningResult(
    val riskScore: Int,
    val confidence: Int,
    val verdict: String,
    val recommendedAction: String,
    val appliedAction: String,
    val mode: String,
    val reason: String?
) {
    fun isDryRun(): Boolean = mode == "DRY_RUN"
    fun shouldApplyBlock(): Boolean = false // Phase 4 never applies block

    companion object {
        fun fromProtocolResponse(resp: Protocol.ScreeningResponse): ScreeningResult {
            return ScreeningResult(
                riskScore = resp.riskScore,
                confidence = resp.confidence,
                verdict = resp.verdict,
                recommendedAction = resp.recommendedAction,
                appliedAction = resp.appliedAction,
                mode = resp.mode,
                reason = resp.reason
            )
        }

        fun unknown(requestId: String, reason: String = "UNKNOWN"): ScreeningResult {
            return ScreeningResult(
                riskScore = 0,
                confidence = 0,
                verdict = "UNKNOWN",
                recommendedAction = "ALLOW",
                appliedAction = "ALLOW",
                mode = "DRY_RUN",
                reason = reason
            )
        }
    }
}

package com.callshield.bridge

import org.junit.Assert.*
import org.junit.Test

class ScreeningResultTest {
    @Test
    fun blockRecommendationStillAppliesAllow() {
        val result = ScreeningResult(
            riskScore = 95,
            confidence = 98,
            verdict = "MALICIOUS",
            recommendedAction = "BLOCK",
            reason = "DRY_RUN",
            latencyMs = 8
        )
        assertEquals("BLOCK", result.recommendedAction)
        assertEquals("ALLOW", result.appliedAction)
        assertEquals("DRY_RUN", result.mode)
        assertFalse(result.shouldApplyBlock())
    }

    @Test
    fun unknownFallbackAllows() {
        val result = ScreeningResult.unknown("DAEMON_UNAVAILABLE")
        assertEquals("UNKNOWN", result.verdict)
        assertEquals("ALLOW", result.recommendedAction)
        assertEquals("ALLOW", result.appliedAction)
    }

    @Test
    fun protocolConversionCannotChangeAppliedAction() {
        val response = Protocol.ScreeningResponse.fallback(
            java.util.UUID.randomUUID().toString(),
            "SCREENING_TIMEOUT"
        )
        val result = ScreeningResult.fromProtocolResponse(response)
        assertEquals("ALLOW", result.appliedAction)
        assertEquals("DRY_RUN", result.mode)
    }
}

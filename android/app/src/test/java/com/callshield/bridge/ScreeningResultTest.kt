package com.callshield.bridge

import org.junit.Assert.*
import org.junit.Test

class ScreeningResultTest {
    @Test
    fun testDryRunNeverBlocks() {
        val resp = Protocol.ScreeningResponse(
            protocol = "callshield/1",
            requestId = "test",
            riskScore = 95,
            confidence = 96,
            verdict = "MALICIOUS",
            recommendedAction = "BLOCK",
            appliedAction = "ALLOW",
            mode = "DRY_RUN"
        )
        val result = ScreeningResult.fromProtocolResponse(resp)
        assertEquals("BLOCK", result.recommendedAction)
        assertEquals("ALLOW", result.appliedAction)
        assertFalse(result.shouldApplyBlock())
        assertTrue(result.isDryRun())
    }

    @Test
    fun testUnknownNumber() {
        val result = ScreeningResult.unknown("req-1", "UNKNOWN")
        assertEquals("UNKNOWN", result.verdict)
        assertEquals("ALLOW", result.appliedAction)
    }

    @Test
    fun testHighRiskDryRun() {
        val result = ScreeningResult(
            riskScore = 87,
            confidence = 92,
            verdict = "HIGH_RISK",
            recommendedAction = "BLOCK",
            appliedAction = "ALLOW",
            mode = "DRY_RUN",
            reason = "Phase 4 dry-run"
        )
        assertEquals("BLOCK", result.recommendedAction)
        assertEquals("ALLOW", result.appliedAction)
    }

    @Test
    fun testSafeNumber() {
        val result = ScreeningResult(
            riskScore = 5,
            confidence = 80,
            verdict = "SAFE",
            recommendedAction = "ALLOW",
            appliedAction = "ALLOW",
            mode = "DRY_RUN",
            reason = "No indicators"
        )
        assertEquals("ALLOW", result.recommendedAction)
        assertEquals("ALLOW", result.appliedAction)
    }

    @Test
    fun testTimeoutHandling() {
        val result = ScreeningResult.unknown("req-timeout", "SCREENING_TIMEOUT")
        assertEquals("UNKNOWN", result.verdict)
        assertEquals("ALLOW", result.appliedAction)
        assertEquals("SCREENING_TIMEOUT", result.reason)
    }
}

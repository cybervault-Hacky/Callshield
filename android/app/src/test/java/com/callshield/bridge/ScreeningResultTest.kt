package com.callshield.bridge

import org.junit.Assert.*
import org.junit.Test
import java.util.UUID

class ScreeningResultTest {
    @Test
    fun activeBlockCanRequestRejection() {
        val result = result(applied = "BLOCK", mode = "ACTIVE")
        assertTrue(result.shouldApplyBlock())
    }

    @Test
    fun activeAllowDoesNotRequestRejection() {
        assertFalse(result(applied = "ALLOW", mode = "ACTIVE").shouldApplyBlock())
    }

    @Test
    fun dryRunNeverRequestsRejection() {
        assertFalse(result(applied = "ALLOW", mode = "DRY_RUN").shouldApplyBlock())
    }

    @Test
    fun emergencyNeverRequestsRejection() {
        val value = ScreeningResult(
            requestId = UUID.randomUUID().toString(),
            riskScore = 100,
            confidence = 100,
            verdict = "MALICIOUS",
            recommendedAction = "BLOCK",
            appliedAction = "BLOCK",
            mode = "ACTIVE",
            reason = "EMERGENCY_OFF",
            latencyMs = 1,
            policyName = "BALANCED",
            emergencyOff = true
        )
        assertFalse(value.shouldApplyBlock())
    }

    @Test
    fun unknownFallbackAllows() {
        val value = ScreeningResult.unknown("DAEMON_UNAVAILABLE")
        assertEquals("ALLOW", value.appliedAction)
        assertFalse(value.shouldApplyBlock())
    }

    private fun result(applied: String, mode: String): ScreeningResult {
        return ScreeningResult(
            requestId = UUID.randomUUID().toString(),
            riskScore = 95,
            confidence = 95,
            verdict = "MALICIOUS",
            recommendedAction = "BLOCK",
            appliedAction = applied,
            mode = mode,
            reason = "test",
            latencyMs = 1,
            policyName = "BALANCED",
            emergencyOff = false
        )
    }
}

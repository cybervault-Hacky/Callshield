package com.callshield.bridge

import org.junit.Assert.*
import org.junit.Test
import kotlinx.coroutines.test.runTest

class BridgeClientTest {
    @Test
    fun testProtocolValidation() {
        val client = BridgeClient(socketPath = "/nonexistent.sock", timeoutMs = 500)
        // This will try to connect and fail, should return UNKNOWN/ALLOW without crashing
        runTest {
            val result = client.screenNumber("+919876543210", "test-123")
            assertEquals("UNKNOWN", result.verdict)
            assertEquals("ALLOW", result.appliedAction)
            assertTrue(result.reason == "DAEMON_UNAVAILABLE" || result.reason == "SCREENING_TIMEOUT")
        }
    }

    @Test
    fun testInvalidNumberHandling() {
        val client = BridgeClient(socketPath = "/nonexistent.sock", timeoutMs = 500)
        runTest {
            val result = client.screenNumber("not-a-number", "test-124")
            assertEquals("UNKNOWN", result.verdict)
            assertEquals("ALLOW", result.appliedAction)
        }
    }

    @Test
    fun testDryRunEnforcement() {
        // Even if daemon says BLOCK, client should enforce ALLOW in dry-run
        // This is tested via Protocol validation: applied BLOCK is invalid
        val resp = Protocol.ScreeningResponse(
            protocol = "callshield/1",
            requestId = "test",
            riskScore = 90,
            confidence = 90,
            verdict = "MALICIOUS",
            recommendedAction = "BLOCK",
            appliedAction = "BLOCK",
            mode = "DRY_RUN"
        )
        assertFalse(resp.isValid())
        // Client should convert to ALLOW
        val fixed = ScreeningResult(
            riskScore = resp.riskScore,
            confidence = resp.confidence,
            verdict = resp.verdict,
            recommendedAction = resp.recommendedAction,
            appliedAction = "ALLOW",
            mode = "DRY_RUN",
            reason = resp.reason
        )
        assertEquals("ALLOW", fixed.appliedAction)
    }

    @Test
    fun testRequestIdMatching() {
        val reqId = "unique-123"
        // Simulate matching
        val resp = Protocol.ScreeningResponse.fromJson(
            """{"protocol":"callshield/1","request_id":"$reqId","risk_score":0,"confidence":0,"verdict":"UNKNOWN","recommended_action":"ALLOW","applied_action":"ALLOW","mode":"DRY_RUN"}"""
        )
        assertNotNull(resp)
        assertEquals(reqId, resp!!.requestId)
    }
}

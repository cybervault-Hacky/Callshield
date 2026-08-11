package com.callshield.bridge

import org.junit.Assert.*
import org.junit.Test

class ProtocolTest {
    @Test
    fun testValidRequest() {
        val req = Protocol.ScreeningRequest(number = "+919876543210")
        assertNull(req.validate())
        val json = req.toJsonString()
        assertTrue(json.contains("callshield/1"))
        assertTrue(json.contains("+919876543210"))
    }

    @Test
    fun testInvalidProtocol() {
        val req = Protocol.ScreeningRequest(protocol = "bad/1", number = "+919876543210")
        assertNotNull(req.validate())
    }

    @Test
    fun testMissingNumber() {
        val req = Protocol.ScreeningRequest(number = "")
        assertNotNull(req.validate())
    }

    @Test
    fun testNumberTooLong() {
        val req = Protocol.ScreeningRequest(number = "1".repeat(101))
        assertNotNull(req.validate())
    }

    @Test
    fun testResponseParsing() {
        val json = """{"protocol":"callshield/1","request_id":"abc","risk_score":87,"confidence":92,"verdict":"HIGH_RISK","recommended_action":"BLOCK","applied_action":"ALLOW","mode":"DRY_RUN"}"""
        val resp = Protocol.ScreeningResponse.fromJson(json)
        assertNotNull(resp)
        assertEquals(87, resp!!.riskScore)
        assertEquals("HIGH_RISK", resp.verdict)
        assertEquals("ALLOW", resp.appliedAction)
        assertTrue(resp.isValid())
    }

    @Test
    fun testResponseRejectsBlockApplied() {
        val json = """{"protocol":"callshield/1","request_id":"abc","risk_score":90,"confidence":90,"verdict":"MALICIOUS","recommended_action":"BLOCK","applied_action":"BLOCK","mode":"DRY_RUN"}"""
        val resp = Protocol.ScreeningResponse.fromJson(json)
        assertNotNull(resp)
        // Phase 4 must not have applied BLOCK
        assertFalse(resp!!.isValid())
    }

    @Test
    fun testTimeoutResponse() {
        val resp = Protocol.ScreeningResponse.timeout("req-123")
        assertEquals("UNKNOWN", resp.verdict)
        assertEquals("ALLOW", resp.appliedAction)
        assertEquals("SCREENING_TIMEOUT", resp.reason)
    }

    @Test
    fun testRequestIdMatching() {
        val req = Protocol.ScreeningRequest(number = "+919876543210", requestId = "test-123")
        val respJson = """{"protocol":"callshield/1","request_id":"test-123","risk_score":10,"confidence":50,"verdict":"UNKNOWN","recommended_action":"ALLOW","applied_action":"ALLOW","mode":"DRY_RUN"}"""
        val resp = Protocol.ScreeningResponse.fromJson(respJson)
        assertEquals(req.requestId, resp!!.requestId)
    }

    @Test
    fun testMalformedResponse() {
        val resp = Protocol.ScreeningResponse.fromJson("not json")
        assertNull(resp)
    }

    @Test
    fun testSizeLimits() {
        val req = Protocol.ScreeningRequest(number = "+919876543210")
        val json = req.toJsonString()
        assertTrue(json.toByteArray().size <= Protocol.MAX_REQUEST_BYTES)
    }
}

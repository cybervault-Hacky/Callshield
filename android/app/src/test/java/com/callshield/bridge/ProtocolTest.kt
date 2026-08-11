package com.callshield.bridge

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.util.UUID

class ProtocolTest {
    @Test
    fun exactAndroidRequestContract() {
        val id = UUID.randomUUID().toString()
        val request = Protocol.ScreeningRequest(requestId = id, number = "+919876543210")
        assertNull(request.validate())
        val json = JSONObject(request.toJsonString())
        assertEquals(setOf("protocol", "request_id", "number", "source"), json.keys().asSequence().toSet())
    }

    @Test
    fun requestValidationRejectsMalformedValues() {
        assertNotNull(Protocol.ScreeningRequest(protocol = "other/1", number = "+919876543210").validate())
        assertNotNull(Protocol.ScreeningRequest(requestId = "bad", number = "+919876543210").validate())
        assertNotNull(Protocol.ScreeningRequest(number = "not-a-number").validate())
    }

    @Test
    fun activeBlockResponseIsValid() {
        val response = Protocol.ScreeningResponse.fromJson(responseJson("BLOCK", "BLOCK", "ACTIVE"))
        assertNotNull(response)
        assertTrue(response!!.isValid())
    }

    @Test
    fun dryRunBlockApplicationIsRejected() {
        assertNull(Protocol.ScreeningResponse.fromJson(responseJson("BLOCK", "BLOCK", "DRY_RUN")))
    }

    @Test
    fun malformedOrUnexpectedDecisionFailsParsing() {
        assertNull(Protocol.ScreeningResponse.fromJson("not-json"))
        assertNull(Protocol.ScreeningResponse.fromJson(responseJson("BLOCK", "INVALID", "ACTIVE")))
        assertNull(Protocol.ScreeningResponse.fromJson(responseJson("BLOCK", "BLOCK", "UNKNOWN")))
    }

    @Test
    fun emergencyCannotApplyBlock() {
        assertNull(
            Protocol.ScreeningResponse.fromJson(
                responseJson("BLOCK", "BLOCK", "ACTIVE", emergency = true)
            )
        )
    }

    @Test
    fun feedbackContractIsBoundedAndValidated() {
        val id = UUID.randomUUID().toString()
        val feedback = Protocol.ScreeningFeedback(id)
        assertTrue(feedback.validate())
        val json = JSONObject(feedback.toJsonString())
        assertEquals("screening_feedback", json.getString("command"))
        assertEquals("REJECTED", json.getString("result"))
    }

    @Test
    fun telNumberNormalizationIsConservative() {
        assertEquals("+919876543210", Protocol.normalizeTelNumber("+91 98765-43210"))
        assertNull(Protocol.normalizeTelNumber(null))
        assertNull(Protocol.normalizeTelNumber("sip:user@example.com"))
    }

    private fun responseJson(
        recommended: String,
        applied: String,
        mode: String,
        emergency: Boolean = false
    ): String {
        return JSONObject().apply {
            put("protocol", "callshield/1")
            put("request_id", UUID.randomUUID().toString())
            put("risk_score", 95)
            put("confidence", 95)
            put("verdict", "MALICIOUS")
            put("recommended_action", recommended)
            put("applied_action", applied)
            put("mode", mode)
            put("reason", "test")
            put("latency_ms", 10)
            put("policy_name", "BALANCED")
            put("threshold", 85)
            put("confidence_threshold", 80)
            put("emergency_off", emergency)
            put("policy_error", false)
        }.toString()
    }
}

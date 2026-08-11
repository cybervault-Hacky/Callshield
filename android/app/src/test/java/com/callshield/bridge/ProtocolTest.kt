package com.callshield.bridge

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.util.UUID

class ProtocolTest {
    @Test
    fun exactAndroidRequestContract() {
        val id = UUID.randomUUID().toString()
        val request = Protocol.ScreeningRequest(
            requestId = id,
            number = "+919876543210"
        )
        assertNull(request.validate())
        val json = JSONObject(request.toJsonString())
        assertEquals(setOf("protocol", "request_id", "number", "source"), json.keys().asSequence().toSet())
        assertEquals("callshield/1", json.getString("protocol"))
        assertEquals(id, json.getString("request_id"))
        assertEquals("+919876543210", json.getString("number"))
        assertEquals("android_call_screening", json.getString("source"))
    }

    @Test
    fun requestValidationRejectsMalformedValues() {
        assertNotNull(Protocol.ScreeningRequest(protocol = "other/1", number = "+919876543210").validate())
        assertNotNull(Protocol.ScreeningRequest(requestId = "bad", number = "+919876543210").validate())
        assertNotNull(Protocol.ScreeningRequest(number = "").validate())
        assertNotNull(Protocol.ScreeningRequest(number = "not-a-number").validate())
        assertNotNull(Protocol.ScreeningRequest(number = "+1" + "2".repeat(20)).validate())
    }

    @Test
    fun telNumberNormalizationIsConservative() {
        assertEquals("+919876543210", Protocol.normalizeTelNumber("+91 98765-43210"))
        assertEquals("+442071838750", Protocol.normalizeTelNumber("0044 20 7183 8750"))
        assertNull(Protocol.normalizeTelNumber(null))
        assertNull(Protocol.normalizeTelNumber(""))
        assertNull(Protocol.normalizeTelNumber("sip:user@example.com"))
    }

    @Test
    fun strictResponseParsesDryRunAllow() {
        val id = UUID.randomUUID().toString()
        val json = """{"protocol":"callshield/1","request_id":"$id","risk_score":92,"confidence":95,"verdict":"MALICIOUS","recommended_action":"BLOCK","applied_action":"ALLOW","mode":"DRY_RUN","reason":"DRY_RUN","latency_ms":12}"""
        val response = Protocol.ScreeningResponse.fromJson(json)
        assertNotNull(response)
        assertEquals("BLOCK", response!!.recommendedAction)
        assertEquals("ALLOW", response.appliedAction)
        assertTrue(response.isValid())
    }

    @Test
    fun responseWithNonAllowAppliedActionIsRejected() {
        val id = UUID.randomUUID().toString()
        val json = """{"protocol":"callshield/1","request_id":"$id","risk_score":92,"confidence":95,"verdict":"MALICIOUS","recommended_action":"BLOCK","applied_action":"BLOCK","mode":"DRY_RUN","reason":"bad","latency_ms":12}"""
        assertNull(Protocol.ScreeningResponse.fromJson(json))
    }

    @Test
    fun malformedResponseFailsParsing() {
        assertNull(Protocol.ScreeningResponse.fromJson("not-json"))
        assertNull(Protocol.ScreeningResponse.fromJson("{}"))
    }

    @Test
    fun fallbackAlwaysAllows() {
        val response = Protocol.ScreeningResponse.fallback("bad-id", "SCREENING_TIMEOUT")
        assertEquals("UNKNOWN", response.verdict)
        assertEquals("ALLOW", response.recommendedAction)
        assertEquals("ALLOW", response.appliedAction)
        assertEquals("DRY_RUN", response.mode)
        assertTrue(response.isValid())
    }
}

package com.callshield.bridge

import org.json.JSONObject
import java.util.UUID

/**
 * Versioned bridge protocol for CALLSHIELD.
 * Protocol: callshield/1
 * No network, no eval, validated fields, size limits.
 */
object Protocol {
    const val VERSION = "callshield/1"
    const val MAX_REQUEST_BYTES = 16 * 1024
    const val MAX_RESPONSE_BYTES = 64 * 1024

    data class ScreeningRequest(
        val protocol: String = VERSION,
        val type: String = "incoming_call",
        val requestId: String = UUID.randomUUID().toString(),
        val number: String,
        val timestamp: String = java.time.Instant.now().toString()
    ) {
        fun toJson(): JSONObject {
            return JSONObject().apply {
                put("protocol", protocol)
                put("type", type)
                put("request_id", requestId)
                put("requestId", requestId) // alias
                put("number", number)
                put("timestamp", timestamp)
            }
        }

        fun toJsonString(): String = toJson().toString()

        fun validate(): String? {
            if (protocol != VERSION) return "Invalid protocol: $protocol"
            if (requestId.isBlank()) return "Missing request_id"
            if (number.isBlank()) return "Missing number"
            if (number.length > 100) return "Number too long"
            // Basic number format check (E.164-ish)
            if (!number.matches(Regex("^\\+?[0-9\\s\\-()\\[\\]/\\\\]+$"))) return "Invalid number format"
            return null
        }
    }

    data class ScreeningResponse(
        val protocol: String,
        val requestId: String,
        val riskScore: Int,
        val confidence: Int,
        val verdict: String,
        val recommendedAction: String,
        val appliedAction: String,
        val mode: String,
        val reason: String? = null,
        val numberMasked: String? = null
    ) {
        companion object {
            fun fromJson(jsonStr: String): ScreeningResponse? {
                return try {
                    val obj = JSONObject(jsonStr)
                    val proto = obj.optString("protocol", VERSION)
                    if (proto != VERSION && proto != "callshield1" && proto != "1") {
                        // Allow but log
                    }
                    val reqId = obj.optString("request_id", obj.optString("requestId", ""))
                    if (reqId.isBlank()) return null
                    ScreeningResponse(
                        protocol = proto,
                        requestId = reqId,
                        riskScore = obj.optInt("risk_score", obj.optInt("riskScore", 0)),
                        confidence = obj.optInt("confidence", 0),
                        verdict = obj.optString("verdict", "UNKNOWN"),
                        recommendedAction = obj.optString("recommended_action", obj.optString("recommendedAction", "ALLOW")),
                        appliedAction = obj.optString("applied_action", obj.optString("appliedAction", "ALLOW")),
                        mode = obj.optString("mode", "DRY_RUN"),
                        reason = obj.optString("reason", null),
                        numberMasked = obj.optString("number_masked", obj.optString("numberMasked", null))
                    )
                } catch (e: Exception) {
                    null
                }
            }

            fun timeout(requestId: String): ScreeningResponse {
                return ScreeningResponse(
                    protocol = VERSION,
                    requestId = requestId,
                    riskScore = 0,
                    confidence = 0,
                    verdict = "UNKNOWN",
                    recommendedAction = "ALLOW",
                    appliedAction = "ALLOW",
                    mode = "DRY_RUN",
                    reason = "SCREENING_TIMEOUT"
                )
            }

            fun error(requestId: String, reason: String): ScreeningResponse {
                return ScreeningResponse(
                    protocol = VERSION,
                    requestId = requestId,
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

        fun isValid(): Boolean {
            if (protocol != VERSION) return false
            if (requestId.isBlank()) return false
            if (verdict !in setOf("SAFE", "UNKNOWN", "SUSPICIOUS", "HIGH_RISK", "MALICIOUS")) return false
            if (recommendedAction !in setOf("ALLOW", "MONITOR", "BLOCK")) return false
            if (appliedAction !in setOf("ALLOW", "MONITOR", "BLOCK")) return false
            // Phase 4 must never have appliedAction = BLOCK
            if (appliedAction == "BLOCK") return false // dry-run enforces ALLOW
            return true
        }
    }
}

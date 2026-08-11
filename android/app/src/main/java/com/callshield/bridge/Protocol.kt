package com.callshield.bridge

import org.json.JSONObject
import java.time.Instant
import java.util.UUID
import kotlin.math.abs

/** Versioned, bounded JSON contract shared with the Termux daemon. */
object Protocol {
    const val VERSION = "callshield/1"
    const val SOURCE_ANDROID = "android_call_screening"
    const val MAX_REQUEST_BYTES = 16 * 1024
    const val MAX_RESPONSE_BYTES = 64 * 1024

    data class ScreeningRequest(
        val protocol: String = VERSION,
        val requestId: String = UUID.randomUUID().toString(),
        val timestamp: String = Instant.now().toString(),
        val number: String,
        val source: String = SOURCE_ANDROID
    ) {
        fun validate(): String? {
            if (protocol != VERSION) return "INVALID_PROTOCOL"
            if (!Protocol.isUuid(requestId)) return "INVALID_REQUEST_ID"
            if (!Protocol.isFreshTimestamp(timestamp)) return "INVALID_TIMESTAMP"
            if (source != SOURCE_ANDROID) return "INVALID_SOURCE"
            if (!number.matches(Regex("^\\+?[0-9]{7,15}$"))) return "INVALID_NUMBER"
            return null
        }

        fun toJsonString(): String = JSONObject().apply {
            put("protocol", protocol)
            put("request_id", requestId)
            put("timestamp", timestamp)
            put("number", number)
            put("source", source)
        }.toString()
    }

    data class ScreeningFeedback(
        val screeningRequestId: String,
        val requestId: String = UUID.randomUUID().toString(),
        val timestamp: String = Instant.now().toString(),
        val result: String = "REJECTED"
    ) {
        fun validate(): Boolean =
            Protocol.isUuid(requestId) &&
                Protocol.isUuid(screeningRequestId) &&
                Protocol.isFreshTimestamp(timestamp) &&
                result == "REJECTED"

        fun toJsonString(): String = JSONObject().apply {
            put("command", "screening_feedback")
            put("protocol", VERSION)
            put("request_id", requestId)
            put("timestamp", timestamp)
            put("screening_request_id", screeningRequestId)
            put("source", SOURCE_ANDROID)
            put("result", result)
        }.toString()
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
        val reason: String,
        val latencyMs: Int,
        val policyName: String,
        val threshold: Int,
        val confidenceThreshold: Int,
        val emergencyOff: Boolean,
        val policyError: Boolean
    ) {
        fun isValid(): Boolean {
            val actionIsValid = appliedAction in setOf("ALLOW", "BLOCK")
            val modeIsValid = mode in setOf("DRY_RUN", "ACTIVE")
            val activeBlockIsValid = appliedAction != "BLOCK" || (
                mode == "ACTIVE" &&
                    recommendedAction == "BLOCK" &&
                    !emergencyOff &&
                    !policyError
                )
            return protocol == VERSION &&
                Protocol.isUuid(requestId) &&
                riskScore in 0..100 &&
                confidence in 0..100 &&
                verdict in setOf("SAFE", "UNKNOWN", "SUSPICIOUS", "HIGH_RISK", "MALICIOUS") &&
                recommendedAction in setOf("ALLOW", "BLOCK") &&
                actionIsValid &&
                modeIsValid &&
                activeBlockIsValid &&
                policyName in setOf("RELAXED", "BALANCED", "STRICT") &&
                threshold in 0..100 &&
                confidenceThreshold in 0..100 &&
                reason.length <= 500 &&
                latencyMs >= 0
        }

        companion object {
            fun fromJson(json: String): ScreeningResponse? {
                return try {
                    val value = JSONObject(json)
                    val required = listOf(
                        "protocol", "request_id", "risk_score", "confidence",
                        "verdict", "recommended_action", "applied_action", "mode",
                        "reason", "latency_ms", "policy_name", "threshold",
                        "confidence_threshold", "emergency_off", "policy_error"
                    )
                    if (required.any { !value.has(it) }) return null
                    ScreeningResponse(
                        protocol = value.getString("protocol"),
                        requestId = value.getString("request_id"),
                        riskScore = value.getInt("risk_score"),
                        confidence = value.getInt("confidence"),
                        verdict = value.getString("verdict"),
                        recommendedAction = value.getString("recommended_action"),
                        appliedAction = value.getString("applied_action"),
                        mode = value.getString("mode"),
                        reason = value.getString("reason"),
                        latencyMs = value.getInt("latency_ms"),
                        policyName = value.getString("policy_name"),
                        threshold = value.getInt("threshold"),
                        confidenceThreshold = value.getInt("confidence_threshold"),
                        emergencyOff = value.getBoolean("emergency_off"),
                        policyError = value.getBoolean("policy_error")
                    ).takeIf { it.isValid() }
                } catch (_: Exception) {
                    null
                }
            }

            fun fallback(requestId: String, reason: String): ScreeningResponse {
                val safeId = if (Protocol.isUuid(requestId)) requestId else UUID.randomUUID().toString()
                return ScreeningResponse(
                    protocol = VERSION,
                    requestId = safeId,
                    riskScore = 0,
                    confidence = 0,
                    verdict = "UNKNOWN",
                    recommendedAction = "ALLOW",
                    appliedAction = "ALLOW",
                    mode = "DRY_RUN",
                    reason = reason.take(500),
                    latencyMs = 0,
                    policyName = "BALANCED",
                    threshold = 100,
                    confidenceThreshold = 100,
                    emergencyOff = true,
                    policyError = false
                )
            }
        }
    }

    fun normalizeTelNumber(raw: String?): String? {
        if (raw.isNullOrBlank()) return null
        val trimmed = raw.trim()
        if (!trimmed.matches(Regex("^[+0-9\\s.()\\[\\]\\-/\\\\]+$"))) return null
        var cleaned = trimmed.replace(Regex("[\\s.()\\[\\]\\-/\\\\]+"), "")
        if (cleaned.startsWith("00")) cleaned = "+" + cleaned.drop(2)
        if (!cleaned.matches(Regex("^\\+?[0-9]{7,15}$"))) return null
        return cleaned
    }

    internal fun isUuid(value: String): Boolean {
        return try {
            UUID.fromString(value)
            true
        } catch (_: IllegalArgumentException) {
            false
        }
    }

    internal fun isFreshTimestamp(value: String): Boolean {
        return try {
            abs(Instant.now().epochSecond - Instant.parse(value).epochSecond) <= 300
        } catch (_: Exception) {
            false
        }
    }
}

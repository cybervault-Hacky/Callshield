package com.callshield.bridge

import org.json.JSONObject
import java.util.UUID

/** Versioned, bounded JSON contract shared with the Termux daemon. */
object Protocol {
    const val VERSION = "callshield/1"
    const val SOURCE_ANDROID = "android_call_screening"
    const val MAX_REQUEST_BYTES = 16 * 1024
    const val MAX_RESPONSE_BYTES = 64 * 1024

    data class ScreeningRequest(
        val protocol: String = VERSION,
        val requestId: String = UUID.randomUUID().toString(),
        val number: String,
        val source: String = SOURCE_ANDROID
    ) {
        fun validate(): String? {
            if (protocol != VERSION) return "INVALID_PROTOCOL"
            if (!Protocol.isUuid(requestId)) return "INVALID_REQUEST_ID"
            if (source != SOURCE_ANDROID) return "INVALID_SOURCE"
            if (!number.matches(Regex("^\\+?[0-9]{7,15}$"))) return "INVALID_NUMBER"
            return null
        }

        fun toJsonString(): String = JSONObject().apply {
            put("protocol", protocol)
            put("request_id", requestId)
            put("number", number)
            put("source", source)
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
        val latencyMs: Int
    ) {
        fun isValid(): Boolean {
            return protocol == VERSION &&
                Protocol.isUuid(requestId) &&
                riskScore in 0..100 &&
                confidence in 0..100 &&
                verdict in setOf("SAFE", "UNKNOWN", "SUSPICIOUS", "HIGH_RISK", "MALICIOUS") &&
                recommendedAction in setOf("ALLOW", "BLOCK", "UNKNOWN") &&
                appliedAction == "ALLOW" &&
                mode == "DRY_RUN" &&
                reason.length <= 500 &&
                latencyMs >= 0
        }

        companion object {
            fun fromJson(json: String): ScreeningResponse? {
                return try {
                    val value = JSONObject(json)
                    val required = listOf(
                        "protocol",
                        "request_id",
                        "risk_score",
                        "confidence",
                        "verdict",
                        "recommended_action",
                        "applied_action",
                        "mode",
                        "reason",
                        "latency_ms"
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
                        latencyMs = value.getInt("latency_ms")
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
                    latencyMs = 0
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
}

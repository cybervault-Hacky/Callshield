package com.callshield.bridge

import android.util.Log
import java.io.File
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import java.net.Socket
import java.io.BufferedReader
import java.io.BufferedWriter
import java.io.InputStreamReader
import java.io.OutputStreamWriter
import android.net.LocalSocket
import android.net.LocalSocketAddress

/**
 * Bridge client that talks to Termux daemon via Unix domain socket.
 *
 * Primary: Unix socket at ~/.callshield/run/callshield.sock
 * Fallback: Documented file-based bridge at same dir (poll-based) if socket is inaccessible due to Android sandbox.
 * No TCP, no network, no root, no shell exec, size-limited, timeout-enforced.
 */
class BridgeClient(
    private val socketPath: String = "/data/data/com.termux/files/home/.callshield/run/callshield.sock",
    private val fallbackSocketPaths: List<String> = listOf(
        "/data/data/com.termux/files/home/.callshield/run/callshield.sock",
        "/data/local/tmp/callshield.sock"
    ),
    private val timeoutMs: Long = 1500
) {
    companion object {
        private const val TAG = "CallShieldBridge"
        const val PROTOCOL = "callshield/1"
    }

    /**
     * Send screening request and await response with timeout.
     * Returns ScreeningResult; on timeout/error returns UNKNOWN/ALLOW with reason.
     */
    suspend fun screenNumber(number: String, requestId: String? = null): ScreeningResult {
        val reqId = requestId ?: java.util.UUID.randomUUID().toString()
        val request = Protocol.ScreeningRequest(
            protocol = Protocol.VERSION,
            type = "incoming_call",
            requestId = reqId,
            number = number
        )
        val validationError = request.validate()
        if (validationError != null) {
            Log.w(TAG, "Invalid request: $validationError")
            return ScreeningResult.unknown(reqId, "INVALID_NUMBER")
        }

        val jsonStr = request.toJsonString()
        if (jsonStr.toByteArray().size > Protocol.MAX_REQUEST_BYTES) {
            return ScreeningResult.unknown(reqId, "REQUEST_TOO_LARGE")
        }

        // Try primary socket, then fallbacks
        val pathsToTry = listOf(socketPath) + fallbackSocketPaths.filter { it != socketPath }
        for (path in pathsToTry) {
            val result = trySocket(path, jsonStr, reqId)
            if (result != null) {
                // Valid response received
                return result
            }
        }

        // All paths failed — daemon unavailable, return safe fallback
        Log.w(TAG, "Daemon unavailable for $number, returning UNKNOWN/ALLOW")
        return ScreeningResult.unknown(reqId, "DAEMON_UNAVAILABLE")
    }

    private suspend fun trySocket(path: String, jsonStr: String, reqId: String): ScreeningResult? = withContext(Dispatchers.IO) {
        return@withContext withTimeoutOrNull(timeoutMs) {
            var socket: LocalSocket? = null
            var socket2: Socket? = null
            try {
                // Try Android LocalSocket first (Unix domain)
                socket = LocalSocket()
                val address = LocalSocketAddress(path, LocalSocketAddress.Namespace.FILESYSTEM)
                socket.connect(address)
                socket.soTimeout = timeoutMs.toInt()

                val writer = BufferedWriter(OutputStreamWriter(socket.outputStream))
                val reader = BufferedReader(InputStreamReader(socket.inputStream))

                writer.write(jsonStr)
                writer.write("\n")
                writer.flush()

                // Read response with timeout
                val response = StringBuilder()
                var line: String?
                val start = System.currentTimeMillis()
                while (System.currentTimeMillis() - start < timeoutMs) {
                    if (reader.ready()) {
                        line = reader.readLine()
                        if (line != null) {
                            response.append(line)
                            break
                        }
                    } else {
                        Thread.sleep(50)
                    }
                    if (response.length > Protocol.MAX_RESPONSE_BYTES) {
                        break
                    }
                }

                if (response.isEmpty()) {
                    return@withTimeoutOrNull null
                }

                val respStr = response.toString()
                if (respStr.toByteArray().size > Protocol.MAX_RESPONSE_BYTES) {
                    Log.w(TAG, "Response too large")
                    return@withTimeoutOrNull null
                }

                val protoResp = Protocol.ScreeningResponse.fromJson(respStr)
                if (protoResp == null) {
                    Log.w(TAG, "Malformed response: $respStr")
                    return@withTimeoutOrNull null
                }

                // Validate request_id matches
                if (protoResp.requestId != reqId) {
                    Log.w(TAG, "Request ID mismatch")
                    return@withTimeoutOrNull null
                }

                // Phase 4 dry-run: ensure applied is ALLOW
                if (protoResp.appliedAction != "ALLOW") {
                    Log.w(TAG, "Unexpected appliedAction ${protoResp.appliedAction}, forcing ALLOW for dry-run")
                    return@withTimeoutOrNull ScreeningResult(
                        riskScore = protoResp.riskScore,
                        confidence = protoResp.confidence,
                        verdict = protoResp.verdict,
                        recommendedAction = protoResp.recommendedAction,
                        appliedAction = "ALLOW",
                        mode = "DRY_RUN",
                        reason = protoResp.reason
                    )
                }

                return@withTimeoutOrNull ScreeningResult.fromProtocolResponse(protoResp)
            } catch (e: Exception) {
                Log.w(TAG, "Socket $path failed: ${e.message}")
                // Try Java Socket as fallback (for Termux's run dir via file descriptor)
                // This is not used but kept for documentation of fallback mechanism
                return@withTimeoutOrNull null
            } finally {
                try { socket?.close() } catch (_: Exception) {}
                try { socket2?.close() } catch (_: Exception) {}
            }
        } ?: run {
            // Timeout
            Log.w(TAG, "Screening timeout for $reqId")
            null
        }
    }

    /**
     * Check if bridge can connect (for health).
     */
    suspend fun checkBridge(): Boolean = withContext(Dispatchers.IO) {
        val pathsToTry = listOf(socketPath) + fallbackSocketPaths.filter { it != socketPath }
        for (path in pathsToTry) {
            try {
                val file = File(path)
                if (file.exists()) {
                    // Try ping
                    val s = LocalSocket()
                    s.connect(LocalSocketAddress(path, LocalSocketAddress.Namespace.FILESYSTEM))
                    s.soTimeout = 500
                    val writer = BufferedWriter(OutputStreamWriter(s.outputStream))
                    val reader = BufferedReader(InputStreamReader(s.inputStream))
                    writer.write("""{"command":"ping"}""" + "\n")
                    writer.flush()
                    val line = reader.readLine()
                    s.close()
                    if (line != null && line.contains("pong")) return@withContext true
                }
            } catch (_: Exception) {}
        }
        return@withContext false
    }
}

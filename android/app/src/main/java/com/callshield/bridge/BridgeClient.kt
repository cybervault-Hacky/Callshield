package com.callshield.bridge

import android.net.LocalSocket
import android.net.LocalSocketAddress
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.nio.charset.CodingErrorAction
import java.nio.charset.StandardCharsets
import java.util.UUID

/** Local Unix-domain-socket client for the existing CALLSHIELD daemon IPC. */
class BridgeClient(
    private val socketPath: String = DEFAULT_TERMUX_SOCKET,
    additionalSocketPaths: List<String> = emptyList(),
    timeoutMs: Int = DEFAULT_TIMEOUT_MS
) {
    companion object {
        const val DEFAULT_TIMEOUT_MS = 1500
        const val DEFAULT_TERMUX_SOCKET =
            "/data/data/com.termux/files/home/.callshield/run/callshield.sock"
    }

    private val effectiveTimeoutMs = timeoutMs.coerceIn(200, 5000)
    private val socketPaths = (listOf(socketPath) + additionalSocketPaths)
        .filter { it.isNotBlank() }
        .distinct()
        .take(4)

    /** Return a fail-open result for every validation, transport, or protocol failure. */
    suspend fun screenNumber(number: String, requestId: String = UUID.randomUUID().toString()): ScreeningResult {
        val started = System.nanoTime()
        val request = Protocol.ScreeningRequest(
            requestId = requestId,
            number = number
        )
        request.validate()?.let { reason ->
            return ScreeningResult.unknown(reason, elapsed(started))
        }
        val encodedRequest = (request.toJsonString() + "\n").toByteArray(StandardCharsets.UTF_8)
        if (encodedRequest.size > Protocol.MAX_REQUEST_BYTES) {
            return ScreeningResult.unknown("REQUEST_TOO_LARGE", elapsed(started))
        }

        val response = withContext(Dispatchers.IO) {
            withTimeoutOrNull(effectiveTimeoutMs.toLong()) {
                for (path in socketPaths) {
                    val candidate = requestOnSocket(path, encodedRequest, requestId)
                    if (candidate != null) return@withTimeoutOrNull candidate
                }
                null
            }
        }
        if (response != null) return response

        val reason = if (elapsed(started) >= effectiveTimeoutMs - 20) {
            "SCREENING_TIMEOUT"
        } else {
            "DAEMON_UNAVAILABLE"
        }
        return ScreeningResult.unknown(reason, elapsed(started))
    }

    /** CONNECTED means only that the daemon's local ping operation answered. */
    suspend fun checkBridge(): Boolean = withContext(Dispatchers.IO) {
        withTimeoutOrNull(500L) {
            for (path in socketPaths) {
                if (pingSocket(path)) return@withTimeoutOrNull true
            }
            false
        } ?: false
    }

    private fun requestOnSocket(
        path: String,
        request: ByteArray,
        requestId: String
    ): ScreeningResult? {
        var socket: LocalSocket? = null
        return try {
            socket = LocalSocket()
            socket.soTimeout = effectiveTimeoutMs
            socket.connect(
                LocalSocketAddress(path, LocalSocketAddress.Namespace.FILESYSTEM)
            )
            socket.soTimeout = effectiveTimeoutMs
            socket.outputStream.write(request)
            socket.outputStream.flush()
            val responseText = readBoundedLine(socket, Protocol.MAX_RESPONSE_BYTES)
                ?: return null
            val response = Protocol.ScreeningResponse.fromJson(responseText)
                ?: return null
            if (response.requestId != requestId) return null
            ScreeningResult.fromProtocolResponse(response)
        } catch (_: Exception) {
            null
        } finally {
            try {
                socket?.close()
            } catch (_: Exception) {
                // Fail-open result is returned by the caller.
            }
        }
    }

    private fun pingSocket(path: String): Boolean {
        var socket: LocalSocket? = null
        return try {
            socket = LocalSocket()
            socket.soTimeout = 500
            socket.connect(
                LocalSocketAddress(path, LocalSocketAddress.Namespace.FILESYSTEM)
            )
            socket.soTimeout = 500
            val ping = "{\"command\":\"ping\"}\n".toByteArray(StandardCharsets.UTF_8)
            socket.outputStream.write(ping)
            socket.outputStream.flush()
            val response = readBoundedLine(socket, 4096)
            response?.contains("\"pong\":true") == true
        } catch (_: Exception) {
            false
        } finally {
            try {
                socket?.close()
            } catch (_: Exception) {
                // The bridge remains fail-open.
            }
        }
    }

    private fun readBoundedLine(socket: LocalSocket, maximumBytes: Int): String? {
        val output = ByteArrayOutputStream()
        while (output.size() <= maximumBytes) {
            val value = socket.inputStream.read()
            if (value == -1 || value == '\n'.code) break
            output.write(value)
        }
        if (output.size() == 0 || output.size() > maximumBytes) return null
        val decoder = StandardCharsets.UTF_8.newDecoder()
            .onMalformedInput(CodingErrorAction.REPORT)
            .onUnmappableCharacter(CodingErrorAction.REPORT)
        return decoder.decode(ByteBuffer.wrap(output.toByteArray())).toString()
    }

    private fun elapsed(started: Long): Int {
        return ((System.nanoTime() - started).coerceAtLeast(0L) / 1_000_000L)
            .coerceAtMost(Int.MAX_VALUE.toLong())
            .toInt()
    }
}

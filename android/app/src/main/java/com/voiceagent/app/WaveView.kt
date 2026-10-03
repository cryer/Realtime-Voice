package com.voiceagent.app

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.os.SystemClock
import android.util.AttributeSet
import android.view.View
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sin

/** 通话波纹：与 web/index.html 同一套视觉（环形 72 条 + 待机呼吸环 + 脉冲环）。 */
class WaveView @JvmOverloads constructor(
    context: Context, attrs: AttributeSet? = null
) : View(context, attrs) {

    enum class State { IDLE, CONNECTING, IN_CALL }

    @Volatile var state = State.IDLE
    @Volatile private var userRms = 0f
    private var userLevel = 0f
    private var agentLevel = 0f
    private val barVals = FloatArray(BARS)
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        strokeCap = Paint.Cap.ROUND
        style = Paint.Style.STROKE
    }
    private val hsv = FloatArray(3)

    fun onUserRms(rms: Float) { userRms = rms }

    fun onAgentRms(rms: Float) {
        agentLevel = max(agentLevel, min(1f, rms * 5f))
    }

    private val anim = object : Runnable {
        override fun run() {
            invalidate()
            if (isAttachedToWindow) postOnAnimation(this)
        }
    }

    override fun onAttachedToWindow() {
        super.onAttachedToWindow()
        postOnAnimation(anim)
    }

    override fun onDetachedFromWindow() {
        removeCallbacks(anim)
        super.onDetachedFromWindow()
    }

    override fun onDraw(canvas: Canvas) {
        val t = SystemClock.uptimeMillis().toFloat()
        val w = width.toFloat()
        val h = height.toFloat()
        val cx = w / 2
        val cy = h / 2
        val s = w / 680f            // 与 web 版 680px 画布同比例
        val r0 = 132f * s

        if (state == State.IDLE) {
            userLevel *= 0.9f
            agentLevel *= 0.9f
            val r = r0 + (sin(t / 900.0).toFloat()) * 4 * s
            paint.strokeWidth = 3 * s
            paint.color = Color.argb(64, 120, 140, 180)
            canvas.drawCircle(cx, cy, r, paint)
            return
        }

        // 脉冲环（connecting 黄 / incall 红）
        val period = if (state == State.CONNECTING) 1100f else 2200f
        val phase = (t % period) / period
        val pr = 88f * s + phase * 60f * s
        val pa = ((1f - phase) * if (state == State.CONNECTING) 128f else 90f).toInt()
        paint.strokeWidth = 4 * s
        paint.color = if (state == State.CONNECTING)
            Color.argb(pa, 217, 165, 20) else Color.argb(pa, 229, 72, 77)
        canvas.drawCircle(cx, cy, pr, paint)

        // 电平：用户=青绿(158)，agent=蓝紫(232)
        userLevel = max(min(1f, userRms * 6f), userLevel * 0.85f)
        agentLevel *= 0.94f
        val level = max(userLevel, agentLevel)
        val speakingAgent = agentLevel > userLevel && agentLevel > 0.02f
        hsv[0] = if (speakingAgent) 232f else 158f
        hsv[1] = 0.75f
        hsv[2] = min(1f, 0.65f + level * 0.3f)
        val base = (6f + level * 64f) * s
        val alpha = ((0.35f + level * 0.6f).coerceIn(0f, 1f) * 255).toInt()

        paint.strokeWidth = 5 * s
        paint.color = Color.HSVToColor(alpha, hsv)
        for (i in 0 until BARS) {
            val wave = 0.55f + 0.45f * sin(t / 260.0 + i * 0.55).toFloat()
            val target = base * wave * (0.7f + 0.3f * sin(t / 130.0 + i * 1.7).toFloat())
            barVals[i] += (target - barVals[i]) * 0.35f
            val a = (i.toDouble() / BARS) * 2 * PI - PI / 2
            val ca = cos(a).toFloat()
            val sa = sin(a).toFloat()
            canvas.drawLine(
                cx + ca * r0, cy + sa * r0,
                cx + ca * (r0 + 10 * s + barVals[i]), cy + sa * (r0 + 10 * s + barVals[i]),
                paint
            )
        }
    }

    private companion object {
        const val BARS = 72
    }
}

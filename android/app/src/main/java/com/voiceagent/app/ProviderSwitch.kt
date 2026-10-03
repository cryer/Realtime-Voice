package com.voiceagent.app

import android.animation.ValueAnimator
import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.LinearGradient
import android.graphics.Paint
import android.graphics.RectF
import android.graphics.Shader
import android.util.AttributeSet
import android.view.MotionEvent
import android.view.View
import android.view.animation.DecelerateInterpolator

/** 「识别/合成 × 本地/云端」分段开关，复刻 web 版玻璃拟态 + 滑动指示器。 */
class ProviderSwitch @JvmOverloads constructor(
    context: Context, attrs: AttributeSet? = null
) : View(context, attrs) {

    private val options = arrayOf("本地", "云端")
    private var label = ""
    private var selected = 0
    private var indPos = 0f
    private var indAnim: ValueAnimator? = null
    var onToggle: ((Int) -> Unit)? = null

    var loading = false
        set(v) {
            field = v
            alpha = if (v) 0.45f else 1f
        }

    private val dp = resources.displayMetrics.density
    private val sp = resources.displayMetrics.scaledDensity

    private val labelPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.argb(140, 255, 255, 255)
        textSize = 12 * sp
        letterSpacing = 0.12f
    }
    private val optPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.argb(140, 255, 255, 255)
        textSize = 12 * sp
    }
    private val selPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.rgb(0x0b, 0x10, 0x20)
        textSize = 12 * sp
        isFakeBoldText = true
    }
    private val boxPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.argb(15, 255, 255, 255)
    }
    private val strokePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = 1f
        color = Color.argb(26, 255, 255, 255)
    }
    private val pillPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.argb(89, 0, 0, 0)
    }
    private val indPaint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val rect = RectF()

    fun setLabel(s: String) { label = s; invalidate() }

    fun selectedIndex() = selected

    fun setSelected(idx: Int) {
        if (idx == selected) return
        selected = idx
        indAnim?.cancel()
        indAnim = ValueAnimator.ofFloat(indPos, idx.toFloat()).apply {
            duration = 280
            interpolator = DecelerateInterpolator()
            addUpdateListener { indPos = it.animatedValue as Float; invalidate() }
            start()
        }
    }

    fun shake() {
        val d = 5 * dp
        ValueAnimator.ofFloat(0f, -d, d, -d * 0.6f, d * 0.6f, 0f).apply {
            duration = 350
            addUpdateListener { translationX = it.animatedValue as Float }
            start()
        }
    }

    private fun pillLeft(w: Float) = w * 0.42f
    private fun pillRight(w: Float) = w - 5 * dp

    override fun onDraw(canvas: Canvas) {
        val w = width.toFloat()
        val h = height.toFloat()
        val r = h / 2

        rect.set(0f, 0f, w, h)
        canvas.drawRoundRect(rect, r, r, boxPaint)
        canvas.drawRoundRect(rect, r, r, strokePaint)

        val ty = h / 2 - (labelPaint.descent() + labelPaint.ascent()) / 2
        canvas.drawText(label, 14 * dp, ty, labelPaint)

        val pl = pillLeft(w)
        val pr = pillRight(w)
        val pad = 5 * dp
        rect.set(pl, pad, pr, h - pad)
        canvas.drawRoundRect(rect, (h - 2 * pad) / 2, (h - 2 * pad) / 2, pillPaint)

        val half = (pr - pl) / 2
        val p3 = 3 * dp
        val l0 = pl + indPos * half + p3
        val r0 = pl + (indPos + 1) * half - p3
        rect.set(l0, pad + p3 / 2, r0, h - pad - p3 / 2)
        indPaint.shader = LinearGradient(
            l0, 0f, r0, h, Color.rgb(0x7d, 0xd3, 0xfc), Color.rgb(0x34, 0xd3, 0x99),
            Shader.TileMode.CLAMP
        )
        canvas.drawRoundRect(rect, h / 2, h / 2, indPaint)

        for (i in 0..1) {
            val p = if (i == selected) selPaint else optPaint
            val textCx = pl + half * (i + 0.5f) - p.measureText(options[i]) / 2
            canvas.drawText(options[i], textCx, ty, p)
        }
    }

    override fun onTouchEvent(e: MotionEvent): Boolean {
        if (e.action == MotionEvent.ACTION_UP && !loading) {
            val w = width.toFloat()
            val pl = pillLeft(w)
            if (e.x > pl) {
                val half = (pillRight(w) - pl) / 2
                val idx = if (e.x < pl + half) 0 else 1
                if (idx != selected) {
                    setSelected(idx)          // 乐观更新，失败由外部 setSelected 回滚
                    onToggle?.invoke(idx)
                }
            }
            performClick()
        }
        return true
    }

    override fun performClick(): Boolean {
        super.performClick()
        return true
    }
}

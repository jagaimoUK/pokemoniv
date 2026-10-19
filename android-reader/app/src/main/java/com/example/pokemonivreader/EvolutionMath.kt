package com.example.pokemonivreader

import kotlin.math.floor
import kotlin.math.sqrt

/** CP prediction bounds derived without knowing the exact level.
 * The current CP is floored, so its unrounded value lies in [CP, CP+1).
 * Evolution retains IVs and level; multiplying by the base-stat ratio yields
 * a conservative evolved-CP integer interval. CP=10 (minimum) is exceptional.
 */
internal object EvolutionMath {
    data class Stats(val attack: Int, val defense: Int, val stamina: Int)
    data class Bounds(val minimum: Int, val maximum: Int) {
        fun verdict(limit: Int = 1500): String = when {
            maximum <= limit -> "OK"
            minimum > limit -> "OVER"
            else -> "UNCERTAIN"
        }
    }
    fun evolvedCp(currentCp: Int, iv: IntArray, from: Stats, to: Stats): Bounds? {
        if (currentCp <= 10 || iv.size != 3 || iv.any { it !in 0..15 }) return null
        if (listOf(from.attack, from.defense, from.stamina, to.attack, to.defense, to.stamina)
                .any { it <= 0 }) return null
        fun power(s: Stats): Double = (s.attack + iv[0]).toDouble() *
                sqrt((s.defense + iv[1]).toDouble()) * sqrt((s.stamina + iv[2]).toDouble())
        val ratio = power(to) / power(from)
        val low = floor(currentCp.toDouble() * ratio).toInt()
        val high = floor((currentCp.toDouble() + 1.0) * ratio).toInt()
        // Upper bound is intentionally inclusive/conservative at integer boundary.
        return Bounds(low, high)
    }
}

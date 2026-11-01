package com.beatbet

import java.net.HttpURLConnection
import java.net.URL
import java.util.Locale

// Kotlin port of round_stats.py

const val DATA_URL = "https://eltorneo.am/data/beatbet"

// Matches per round -> minimum count on each side (favourite wins / does not win)
// for a round to be positive. E.g. 8 matches: 3 5, 4 4 and 5 3 are positive.
val MIN_SIDE_BY_MATCHES = mapOf(12 to 5, 11 to 4, 10 to 4, 9 to 3, 8 to 3, 7 to 2, 6 to 2)

/** (fav wins, fav not wins) of one round. */
data class Split(val wins: Int, val notWins: Int) {
    val total get() = wins + notWins
}

/** Positive rounds when each side needs at least minSide, e.g. 9 matches with minSide 3: "3 6 .. 6 3". */
data class PatternStats(
    val matches: Int,
    val minSide: Int,
    val positive: Int,
    val total: Int,
    val percentage: Double,
) {
    val text get() = "$minSide ${matches - minSide} .. ${matches - minSide} $minSide"
}

data class LeagueStats(
    val positive: Int,
    val total: Int,
    val percentage: Double,
    /** (round number, split) of the latest round if it is unfinished, otherwise null. */
    val currentRound: Pair<Int, Split>?,
    /** Every pattern from "1 n-1 .. n-1 1" up to the most balanced one. */
    val patterns: List<PatternStats> = emptyList(),
    /** minSide of the default pattern for the league's matches per round. */
    val defaultMinSide: Int? = null,
)

/** Download <DATA_URL>/<leagueId>.txt. Blocking, so call it off the main thread. */
fun downloadRounds(leagueId: Int): String {
    val connection = URL("$DATA_URL/$leagueId.txt").openConnection() as HttpURLConnection
    connection.connectTimeout = 15_000
    connection.readTimeout = 15_000
    // Never show a stale copy of a file the user just updated
    connection.useCaches = false
    try {
        if (connection.responseCode != 200) {
            error("Server returned ${connection.responseCode} for $leagueId.txt")
        }
        return connection.inputStream.bufferedReader(Charsets.UTF_8).readText()
    } finally {
        connection.disconnect()
    }
}

/** Parse a round file into {round number: split}. */
fun parseRounds(text: String): Map<Int, Split> {
    val rounds = mutableMapOf<Int, Split>()
    var currentRound: Int? = null
    for (rawLine in text.lines()) {
        val line = rawLine.trim()
        if (line.isEmpty()) continue
        if (line.startsWith("r")) {
            currentRound = line.substring(1).toInt()
        } else {
            val (wins, notWins) = line.split(Regex("\\s+")).map { it.toInt() }
            val round = currentRound ?: error("Numbers before the first round line: \"$line\"")
            rounds[round] = Split(wins, notWins)
        }
    }
    return rounds
}

/** Largest round total, so an incomplete round does not lower it. */
fun matchesPerRound(rounds: Map<Int, Split>): Int = rounds.values.maxOf { it.total }

/** Both sides reach the minimum, even if some matches of the round are missing.
 * minSide overrides the default minimum for the league's matches per round. */
fun isPositive(split: Split, matches: Int, minSide: Int = MIN_SIDE_BY_MATCHES.getValue(matches)): Boolean {
    return split.wins >= minSide && split.notWins >= minSide
}

/** Number of the latest round if not all its matches are played yet, otherwise null. */
private fun unfinishedCurrentRound(rounds: Map<Int, Split>): Int? {
    if (rounds.isEmpty()) return null
    val number = rounds.keys.max()
    return if (rounds.getValue(number).total == matchesPerRound(rounds)) null else number
}

fun leagueStats(leagueId: Int, rounds: Map<Int, Split>): LeagueStats {
    if (rounds.isEmpty()) return LeagueStats(0, 0, 0.0, null)
    val matches = matchesPerRound(rounds)
    if (matches !in MIN_SIDE_BY_MATCHES) {
        error("League $leagueId: no pattern defined for $matches matches per round")
    }
    val unfinished = unfinishedCurrentRound(rounds)
    val finished = rounds.filterKeys { it != unfinished }
    val positive = finished.values.count { isPositive(it, matches) }
    val total = finished.size
    val percentage = if (total == 0) 0.0 else positive.toDouble() / total * 100
    val current = unfinished?.let { it to rounds.getValue(it) }
    val patterns = (1..matches / 2).map { minSide ->
        val patternPositive = finished.values.count { isPositive(it, matches, minSide) }
        val patternPercentage = if (total == 0) 0.0 else patternPositive.toDouble() / total * 100
        PatternStats(matches, minSide, patternPositive, total, patternPercentage)
    }
    return LeagueStats(positive, total, percentage, current, patterns, MIN_SIDE_BY_MATCHES.getValue(matches))
}

/** Same lines as print_league_stats in main.py. */
fun formatStats(league: League, stats: LeagueStats): String = buildString {
    val percentage = String.format(Locale.US, "%.2f", stats.percentage)
    append(
        "${league.name} (${league.id}): ${stats.positive} positive, " +
            "${stats.total - stats.positive} negative, ${stats.total} total " +
            "($percentage% fit the pattern)"
    )
    stats.currentRound?.let { (number, split) ->
        append("\n    current round r$number: ${split.wins} ${split.notWins}")
    }
    if (stats.patterns.isNotEmpty()) append("\n\nAll patterns:")
    for (pattern in stats.patterns) {
        val patternPercentage = String.format(Locale.US, "%6.2f", pattern.percentage)
        val default = if (pattern.minSide == stats.defaultMinSide) "  (default)" else ""
        append("\n    ${pattern.text}: $patternPercentage%  ${pattern.positive}/${pattern.total}$default")
    }
}

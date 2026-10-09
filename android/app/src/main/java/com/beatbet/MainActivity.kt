package com.beatbet

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            MaterialTheme {
                var selected by remember { mutableStateOf<League?>(null) }
                val league = selected
                if (league == null) {
                    LeagueListScreen(onSelect = { selected = it })
                } else {
                    BackHandler { selected = null }
                    LeagueScreen(league, onBack = { selected = null })
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LeagueListScreen(onSelect: (League) -> Unit) {
    Scaffold(topBar = { TopAppBar(title = { Text("Leagues") }) }) { padding ->
        LazyColumn(Modifier.padding(padding)) {
            items(LEAGUES, key = { it.id }) { league ->
                Text(
                    league.name,
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable { onSelect(league) }
                        .padding(horizontal = 16.dp, vertical = 14.dp),
                    style = MaterialTheme.typography.bodyLarge,
                )
                HorizontalDivider()
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LeagueScreen(league: League, onBack: () -> Unit) {
    // Bumped by Refresh to download the file again
    var reload by remember { mutableIntStateOf(0) }
    var output by remember { mutableStateOf<String?>(null) }
    var failure by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(league.id, reload) {
        output = null
        failure = null
        try {
            output = withContext(Dispatchers.IO) {
                formatStats(league, leagueStats(league.id, parseRounds(downloadRounds(league.id))))
            }
        } catch (e: Exception) {
            failure = e.message ?: e.toString()
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(league.name) },
                navigationIcon = { TextButton(onClick = onBack) { Text("Back") } },
                actions = { TextButton(onClick = { reload++ }) { Text("Refresh") } },
            )
        },
    ) { padding ->
        Box(
            Modifier
                .padding(padding)
                .fillMaxSize()
                .padding(16.dp),
        ) {
            val text = output
            val error = failure
            when {
                text != null -> Text(
                    text,
                    modifier = Modifier.verticalScroll(rememberScrollState()),
                    fontFamily = FontFamily.Monospace,
                    fontSize = 14.sp,
                )
                error != null -> Column(
                    Modifier.align(Alignment.Center),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    Text("Could not load the league: $error")
                    Button(onClick = { reload++ }) { Text("Try again") }
                }
                else -> CircularProgressIndicator(Modifier.align(Alignment.Center))
            }
        }
    }
}

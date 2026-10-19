package com.example.pokemonivreader

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Test

class IvSelectionTextTest {
    @Test fun sharedTransferContract() {
        // Gradle may use the root project or the app module as its working directory.
        val fixture = listOf(File("contracts/iv-text-v1.tsv"), File("../contracts/iv-text-v1.tsv"))
            .first { it.isFile }
        fixture.readLines(Charsets.UTF_8).drop(1).filter { it.isNotBlank() }.forEach { line ->
            val fields = line.split('\t')
            val targets = fields[1].split('|')
            val ivs = fields[4].split('|')
            val expected = "個体値厳選\n\n# ${fields[2]}\n${ivs.joinToString("\n")}"
            assertEquals(fields[0], expected, IvSelectionText.prompt(listOf(IvSelectionText.Group(targets, ivs))))
            // Re-exporting the canonical form must not duplicate the shadow prefix.
            assertEquals(fields[0], fields[2], targets.joinToString(" ") {
                IvSelectionText.targetName(IvSelectionText.targetName(it))
            })
        }
    }

    @Test fun emptyGroupsDoNotProduceCommands() {
        assertEquals("", IvSelectionText.prompt(emptyList()))
        assertEquals("", IvSelectionText.prompt(listOf(IvSelectionText.Group(emptyList(), listOf("1,2,3")))))
    }

    @Test fun independentGroupsKeepTheirOwnIvs() {
        assertEquals("個体値厳選\n\n# キバニア\n1,2,3\n\n# シャドウサメハダー\n4,5,6",
            IvSelectionText.prompt(listOf(
                IvSelectionText.Group(listOf("キバニア"), listOf("1,2,3")),
                IvSelectionText.Group(listOf("サメハダー (シャドウ)"), listOf("4,5,6")))))
    }
}

package com.example.pokemonivreader

import java.io.File

/** Execute the actual reader serializer, then let the Python importer consume it. */
fun main(args: Array<String>) {
    val output = File(args[1]).apply { mkdirs() }
    File(args[0]).readLines(Charsets.UTF_8).drop(1).filter { it.isNotBlank() }.forEach { line ->
        val fields = line.split('\t')
        val targets = fields[1].split('|')
        val ivs = fields[4].split('|')
        val text = IvSelectionText.prompt(listOf(IvSelectionText.Group(targets, ivs)))
        val expected = "個体値厳選\n\n# ${fields[2]}\n${ivs.joinToString("\n")}"
        check(text == expected) { "${fields[0]}: unexpected reader output: $text" }
        check(targets.joinToString(" ") {
            IvSelectionText.targetName(IvSelectionText.targetName(it))
        } == fields[2]) { "${fields[0]}: shadow prefix duplicated" }
        File(output, fields[0] + ".txt").writeText(text, Charsets.UTF_8)
    }
    check(IvSelectionText.prompt(emptyList()) == "")
    check(IvSelectionText.prompt(listOf(IvSelectionText.Group(emptyList(), listOf("1,2,3")))) == "")
    check(IvSelectionText.prompt(listOf(
        IvSelectionText.Group(listOf("キバニア"), listOf("1,2,3")),
        IvSelectionText.Group(listOf("サメハダー (シャドウ)"), listOf("4,5,6")))) ==
        "個体値厳選\n\n# キバニア\n1,2,3\n\n# シャドウサメハダー\n4,5,6")
    println("Reader serializer: all shared contract cases passed")
}

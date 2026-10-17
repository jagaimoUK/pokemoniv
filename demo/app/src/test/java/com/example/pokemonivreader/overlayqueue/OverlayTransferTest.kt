package com.example.pokemonivreader.overlayqueue

import com.example.pokemonivreader.IvSelectionText
import org.junit.Assert.*
import org.junit.Test

class OverlayTransferTest {
    @Test fun structuredTransferKeepsExactIvsAndCp() {
        val data = """{"format":"pokemoniv-overlay-v2","items":[{"search":"Wooper&0attack&3defense&3hp&cp717","nickname":"AQuag>Cor01","ivs":"0/11/12","cp":717}]}"""
        val item = OverlayPairParser.parse(data).single()
        assertEquals("0/11/12", item.ivs)
        assertEquals("Wooper&0attack&3defense&3hp&cp717", item.searchText)
        assertEquals("AQuag>Cor01", item.nickname)
        assertEquals(2, OverlayPairParser.parse(data.replace("}]", "}," + data.substringAfter("[").substringBeforeLast("]") + "]")).size)
    }
    @Test fun legacyPairsDoNotInventExactIvs() {
        val items = OverlayPairParser.parse("Quagsire&0attack&3defense&3hp\nAQuag>Cor01\n")
        assertNull(items.single().ivs)
        assertEquals("攻0 / 防11〜14 / HP11〜14", OverlayPairParser.legacyIvLabel(items.single().searchText))
    }
    @Test fun malformedMetadataRejectsWholeImport() {
        for (data in listOf(
            """{"format":"pokemoniv-overlay-v2","items":[{"search":"Wooper&cp718","nickname":"A","ivs":"0/11/12","cp":717}]}""",
            """{"format":"pokemoniv-overlay-v2","items":[{"search":"Wooper","nickname":"A","ivs":"16/11/12"}]}""",
            "search\nname\nextra", "search\n")) {
            try { OverlayPairParser.parse(data); fail("Expected rejection") } catch (_: OverlayPairFormatException) {}
        }
    }
    @Test fun readerExportKeepsObservedCpAndShadowSource() {
        assertEquals("0,11,12 CP717 | シャドウウパー", IvSelectionText.individual("0,11,12",717,"ウパー (シャドウ)"))
        val text = IvSelectionText.prompt(listOf(IvSelectionText.Group(listOf("ウパー", "ヌオー"),
            listOf(IvSelectionText.individual("0,11,12",717,"ウパー")))))
        assertEquals("個体値厳選\n\n# ウパー ヌオー\n0,11,12 CP717 | ウパー", text)
    }
}

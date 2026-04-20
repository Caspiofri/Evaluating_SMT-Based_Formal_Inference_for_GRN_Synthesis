// RE:IN Engine v2 Runner — dotnet fsi script
// Usage: dotnet fsi vm/engine_v2_runner.fsx -- <rein_file> <max_solutions> <traj_length>
// Writes analysis_data.json next to the .rein file.
#r "/home/caspiofri/submission/artifact/RENotebookApi/bin/Release/netstandard2.0/REIN.dll"
#r "/home/caspiofri/submission/artifact/RENotebookApi/bin/Release/netstandard2.0/RENotebookApi.dll"
#r "/home/caspiofri/submission/artifact/RENotebookApi/bin/Release/netstandard2.0/ReasoningEngine.dll"
#r "/home/caspiofri/submission/artifact/RENotebookApi/bin/Release/netstandard2.0/FsLexYacc.Runtime.dll"
#r "/home/caspiofri/submission/artifact/RENotebookApi/bin/Release/netstandard2.0/RESIN.dll"
#r "/home/caspiofri/submission/artifact/RENotebookApi/bin/Release/netstandard2.0/ReinMoCo.dll"
// libz3.dll is a native library — loaded automatically at runtime, not via #r
#r "/home/caspiofri/.nuget/packages/microsoft.z3.x64/4.8.9/lib/netstandard1.4/Microsoft.Z3.dll"
#r "/home/caspiofri/.nuget/packages/newtonsoft.json/12.0.2/lib/netstandard2.0/Newtonsoft.Json.dll"
#r "/home/caspiofri/.nuget/packages/automaticgraphlayout.drawing/1.1.9/lib/netstandard2.0/AutomaticGraphLayout.Drawing.dll"
#r "/home/caspiofri/.nuget/packages/automaticgraphlayout/1.1.9/lib/netstandard2.0/AutomaticGraphLayout.dll"

open System
open System.IO
open System.Collections.Generic
open Newtonsoft.Json

// Helper types
type SpeciesRecord = { name: string; lVar: string }

type ConclusionData = {
    ``Gene Name``: string
    ``Internal Variable``: string
    ``Assigned Value``: string
}

type BehaviorRecord = {
    ``Experiment Name``: string
    ``Detected Behavior``: string
    ``Final State String``: string
    time_step: int option
    gene_configuration: string option
}

type PathState = { time: int; state: Dictionary<string, string> }

type SolutionData = {
    varmap: Dictionary<string, string>
    paths: Dictionary<string, PathState list>
}

// Per-solution edge and L-value data
type EdgeRecord = {
    source: string
    target: string
    sign: string
    is_optional: bool
}

type SpeciesLValue = {
    name: string
    lvalue: int
}

type SolutionDetail = {
    solution_index: int
    species_lvalues: SpeciesLValue list
    active_edges: EdgeRecord list
}

type EdgeFrequency = {
    source: string
    target: string
    sign: string
    count: int
    frequency: float
}

type RemovalResult = {
    source: string
    target: string
    sign: string
    status: string
}

let jsonSettings () =
    let s = JsonSerializerSettings()
    s.NullValueHandling <- NullValueHandling.Include
    s.DefaultValueHandling <- DefaultValueHandling.Include
    s

let createErrorJson (errorMsg: string) =
    let o = dict [
        ("error",            box errorMsg)
        ("network_svg",      box "")
        ("solution_svg",     box "")
        ("summary_html",     box "")
        ("observations_html",box "")
        ("required_html",    box "")
        ("constrained_svg",  box "")
        ("required_count",   box 0)
        ("disallowed_count", box 0)
        ("minimal_html",     box "")
        ("minimal_count",    box 0)
        ("rawSolutions",     box "")
        ("speciesList",      box (List<SpeciesRecord>()))
        ("solutions",        box (List<SolutionDetail>()))
        ("edge_frequency",   box (List<EdgeFrequency>()))
        ("solutionCount",    box 0)
        ("removal_required", box (List<RemovalResult>()))
        ("conclusion_data",  box (List<ConclusionData>()))
        ("steady_states",    box (List<BehaviorRecord>()))
        ("oscillations",     box (List<BehaviorRecord>()))
    ]
    JsonConvert.SerializeObject(o, Formatting.None, jsonSettings())

let writeErrorOutput (outputPath: string) (errorMsg: string) =
    try File.WriteAllText(outputPath, createErrorJson errorMsg)
    with ex ->
        try
            let fb = Path.Combine(Directory.GetCurrentDirectory(), "analysis_data.json")
            File.WriteAllText(fb, createErrorJson (sprintf "%s (write error: %s)" errorMsg ex.Message))
        with _ -> eprintfn "Critical: could not write error JSON"

let main (argv: string[]) =
    if argv.Length < 3 then
        eprintfn "Usage: dotnet fsi engine_v2_runner.fsx -- <rein_file> <max_solutions> <traj_length> [--deep]"
        2
    else
        let reinFile    = argv.[0]
        let maxSolutions = Int32.Parse(argv.[1])
        let trajLength   = Int32.Parse(argv.[2])
        let deepAnalysis = argv |> Array.exists (fun a -> a = "--deep")
        let allSvgs     = argv |> Array.exists (fun a -> a = "--all-svgs")
        let doRemoval   = argv |> Array.exists (fun a -> a = "--removal")

        let reinAbs =
            if Path.IsPathRooted(reinFile) then reinFile
            else Path.GetFullPath(Path.Combine(Directory.GetCurrentDirectory(), reinFile))

        let outDir  = Path.GetDirectoryName(reinAbs)
        let outPath = Path.Combine(outDir, "analysis_data.json")

        if not (File.Exists(reinAbs)) then
            let msg = sprintf "Error: file not found: %s" reinAbs
            eprintfn "%s" msg
            if Directory.Exists(outDir) then writeErrorOutput outPath msg
            2
        elif not (Directory.Exists(outDir)) then
            let msg = sprintf "Error: output dir missing: %s" outDir
            eprintfn "%s" msg
            1
        else
            try
                // The REIN lexer is ASCII-only and cannot handle:
                //   (a) non-ASCII bytes (em dashes, etc.)
                //   (b) forward-slash '/' characters inside // comment text
                //       (treated as start of another token by the lexer)
                // Fix: strip non-ASCII bytes, then blank out all // comment lines.
                let rawBytes = File.ReadAllBytes(reinAbs)
                let asciiStr =
                    rawBytes
                    |> Array.map (fun b -> if b > 127uy then 32uy else b)
                    |> System.Text.Encoding.ASCII.GetString
                // Also replace any remaining '/' with space — the REIN lexer treats
                // a bare '/' (outside //) as an unexpected token, including inside "..." labels.
                let cleaned =
                    asciiStr.Split('\n')
                    |> Array.map (fun line ->
                        let t = line.TrimStart()
                        if t.StartsWith("//") then ""
                        else line.Replace('/', ' '))
                    |> String.concat "\n"
                let tempRein = Path.GetTempFileName() + ".rein"
                File.WriteAllText(tempRein, cleaned)
                let problem =
                    try Microsoft.Research.RENotebook.REIN.LoadFile tempRein
                    finally try File.Delete(tempRein) with _ -> ()
                let effTraj = max trajLength 30
                let prob =
                    { problem with
                        settings =
                            { problem.settings with
                                uniqueness = Microsoft.Research.REIN.Settings.Uniqueness.Interactions
                                traj_length = effTraj } }

                let sw = System.Diagnostics.Stopwatch.StartNew()
                let solutions = Microsoft.Research.RENotebook.REIN.Enumerate maxSolutions prob |> Seq.toArray
                eprintfn "TIMING: Enumerate %d solutions: %dms" solutions.Length sw.ElapsedMilliseconds

                let speciesList: SpeciesRecord list =
                    prob.species
                    |> Seq.map (fun s -> { name = s.name; lVar = if isNull s.lVar then "" else s.lVar })
                    |> Seq.toList

                // Extract per-solution edge activation and L-value data
                let solutionDetails: SolutionDetail list =
                    solutions
                    |> Array.mapi (fun i sol ->
                        let lvalues =
                            sol.species
                            |> Seq.map (fun s ->
                                let lv =
                                    match s.reg_conds with
                                    | Some lst ->
                                        match lst |> Seq.tryHead with
                                        | Some v -> v
                                        | None   -> -1
                                    | None -> -1
                                { name = s.name; lvalue = lv }
                            )
                            |> Seq.toList
                        let edges =
                            sol.interactions
                            |> Seq.map (fun inter ->
                                { source = inter.source
                                  target = inter.target
                                  sign = if inter.positive then "positive" else "negative"
                                  is_optional = not inter.definite }
                            )
                            |> Seq.toList
                        { solution_index = i
                          species_lvalues = lvalues
                          active_edges = edges }
                    )
                    |> Array.toList

                // Compute edge frequency across all solutions
                let edgeFrequencies: EdgeFrequency list =
                    if solutions.Length = 0 then []
                    else
                        let allEdges =
                            solutionDetails
                            |> List.collect (fun sd -> sd.active_edges)
                            |> List.map (fun e -> (e.source, e.target, e.sign))
                        let counts =
                            allEdges
                            |> List.groupBy id
                            |> List.map (fun ((src, tgt, sign), occurrences) ->
                                { source = src
                                  target = tgt
                                  sign = sign
                                  count = occurrences.Length
                                  frequency = float occurrences.Length / float solutions.Length }
                            )
                            |> List.sortByDescending (fun ef -> ef.frequency)
                        counts

                // SVG/HTML generation — each wrapped in try/with for graceful fallback.
                // DrawBespokeNetworkWithSizeSVG requires SixLabors.Fonts at runtime.

                // 1. Problem-level network (all edges, optional shown dashed)
                let networkSvg =
                    try
                        let (Microsoft.Research.RENotebook.Lib.HtmlOutput svg) =
                            Microsoft.Research.RENotebook.REIN.DrawBespokeNetworkWithSizeSVG 600.0 prob
                        svg
                    with ex ->
                        eprintfn "network_svg failed: %s" ex.Message
                        ""

                // 2. Solution networks (one SVG per solution)
                let solutionSvg =
                    try
                        if solutions.Length > 0 then
                            let (Microsoft.Research.RENotebook.Lib.HtmlOutput svg) =
                                solutions.[0] |> Microsoft.Research.RENotebook.REIN.DrawBespokeNetworkWithSizeSVG 600.0
                            svg
                        else ""
                    with ex ->
                        eprintfn "solution_svg failed: %s" ex.Message
                        ""

                let solutionSvgs =
                    if not allSvgs then
                        eprintfn "Skipping all-solution SVGs (no --all-svgs flag)"
                        [||]
                    else
                    try
                        let swSvgs = System.Diagnostics.Stopwatch.StartNew()
                        eprintfn "Generating SVGs for %d solutions..." solutions.Length
                        let result =
                            solutions |> Array.map (fun sol ->
                                try
                                    let (Microsoft.Research.RENotebook.Lib.HtmlOutput svg) =
                                        sol |> Microsoft.Research.RENotebook.REIN.DrawBespokeNetworkWithSizeSVG 600.0
                                    svg
                                with _ -> ""
                            )
                        eprintfn "TIMING: All solution SVGs: %dms" swSvgs.ElapsedMilliseconds
                        result
                    with _ -> [||]

                // 3. Summary table (interaction matrix across all solutions)
                let summaryHtml =
                    try
                        if solutions.Length > 0 then
                            let (Microsoft.Research.RENotebook.Lib.HtmlOutput h) =
                                Microsoft.Research.RENotebook.REIN.DrawSummary solutions
                            h
                        else
                            let (Microsoft.Research.RENotebook.Lib.HtmlOutput h) =
                                Microsoft.Research.RENotebook.REIN.ProblemToHtml prob
                            h
                    with _ -> ""

                // 4. Observations table (experimental constraints)
                let observationsHtml =
                    try
                        let (Microsoft.Research.RENotebook.Lib.HtmlOutput h) =
                            prob |> Microsoft.Research.RENotebook.REIN.DrawObservations
                        h
                    with _ -> ""

                // 5. IdentifyInteractions — find required and disallowed edges (--deep only)
                let requiredHtml, constrainedSvg, requiredCount, disallowedCount =
                    if not deepAnalysis then
                        eprintfn "Skipping IdentifyInteractions (no --deep flag)"
                        "", "", 0, 0
                    else
                    try
                        let swId = System.Diagnostics.Stopwatch.StartNew()
                        eprintfn "Running IdentifyInteractions..."
                        let constrainedABN, required, disallowed =
                            prob |> Microsoft.Research.RENotebook.REIN.IdentifyInteractions
                        let reqArr = required |> Seq.toArray
                        let disArr = disallowed |> Seq.toArray
                        let (Microsoft.Research.RENotebook.Lib.HtmlOutput interactionsHtml) =
                            Microsoft.Research.RENotebook.REIN.DrawInteractions reqArr disArr
                        let csvg =
                            try
                                let (Microsoft.Research.RENotebook.Lib.HtmlOutput s) =
                                    constrainedABN |> Microsoft.Research.RENotebook.REIN.DrawBespokeNetworkWithSizeSVG 600.0
                                s
                            with _ -> ""
                        eprintfn "TIMING: IdentifyInteractions: %dms (%d required, %d disallowed)" swId.ElapsedMilliseconds reqArr.Length disArr.Length
                        interactionsHtml, csvg, reqArr.Length, disArr.Length
                    with ex ->
                        eprintfn "IdentifyInteractions failed: %s" ex.Message
                        "", "", 0, 0

                // 6. FindMinimalModels — find consistent networks with fewest edges (--deep only)
                let minimalHtml, minimalCount, minimalSvgs =
                    if not deepAnalysis then
                        eprintfn "Skipping FindMinimalModels (no --deep flag)"
                        "", 0, [||]
                    else
                    try
                        let swMin = System.Diagnostics.Stopwatch.StartNew()
                        eprintfn "Running FindMinimalModels..."
                        let minimalModels =
                            prob
                            |> Microsoft.Research.RENotebook.REIN.FindMinimalModels
                            |> Seq.toArray
                        let (Microsoft.Research.RENotebook.Lib.HtmlOutput h) =
                            minimalModels |> Microsoft.Research.RENotebook.REIN.DrawSummary
                        let svgs =
                            minimalModels |> Array.map (fun m ->
                                try
                                    let (Microsoft.Research.RENotebook.Lib.HtmlOutput s) =
                                        m |> Microsoft.Research.RENotebook.REIN.DrawBespokeNetworkWithSizeSVG 600.0
                                    s
                                with _ -> ""
                            )
                        eprintfn "TIMING: FindMinimalModels: %dms (%d models, %d SVGs)" swMin.ElapsedMilliseconds minimalModels.Length svgs.Length
                        h, minimalModels.Length, svgs
                    with ex ->
                        eprintfn "FindMinimalModels failed: %s" ex.Message
                        "", 0, [||]

                // 7. Removal-UNSAT protocol — test each optional edge (--removal only)
                // For each optional interaction, remove it from the problem and test SAT.
                // If UNSAT (0 solutions) → edge is REQUIRED.
                // NOTE: RemoveInteractions(source, target) removes ALL edges between that
                // gene pair regardless of sign. Safe when at most one edge per pair exists.
                let removalResults: RemovalResult list =
                    if not doRemoval then
                        eprintfn "Skipping removal protocol (no --removal flag)"
                        []
                    else
                    try
                        let swRem = System.Diagnostics.Stopwatch.StartNew()
                        let optionalEdges =
                            prob.interactions
                            |> Seq.filter (fun i -> not i.definite)
                            |> Seq.toArray
                        eprintfn "Running removal protocol on %d optional edges..." optionalEdges.Length
                        let results =
                            optionalEdges
                            |> Array.map (fun inter ->
                                let modifiedProb = prob.RemoveInteractions(inter.source, inter.target)
                                let testSolutions =
                                    Microsoft.Research.RENotebook.REIN.Enumerate 1 modifiedProb |> Seq.toArray
                                let status = if testSolutions.Length = 0 then "REQUIRED" else "SAT"
                                eprintfn "  %s %s %s → %s" inter.source (if inter.positive then "positive" else "negative") inter.target status
                                { source = inter.source
                                  target = inter.target
                                  sign = if inter.positive then "positive" else "negative"
                                  status = status }
                            )
                            |> Array.toList
                        let reqCount = results |> List.filter (fun r -> r.status = "REQUIRED") |> List.length
                        eprintfn "TIMING: Removal protocol: %dms (%d required, %d SAT)" swRem.ElapsedMilliseconds reqCount (results.Length - reqCount)
                        results
                    with ex ->
                        eprintfn "Removal protocol failed: %s" ex.Message
                        []

                let outputObj = dict [
                    ("error",            box null)
                    ("network_svg",      box networkSvg)
                    ("solution_svg",     box solutionSvg)
                    ("solution_svgs",    box solutionSvgs)
                    ("summary_html",     box summaryHtml)
                    ("observations_html",box observationsHtml)
                    ("required_html",    box requiredHtml)
                    ("constrained_svg",  box constrainedSvg)
                    ("required_count",   box requiredCount)
                    ("disallowed_count", box disallowedCount)
                    ("minimal_html",     box minimalHtml)
                    ("minimal_count",    box minimalCount)
                    ("minimal_svgs",     box minimalSvgs)
                    ("rawSolutions",     box (sprintf "%A" solutions))
                    ("speciesList",      box speciesList)
                    ("solutions",        box solutionDetails)
                    ("edge_frequency",   box edgeFrequencies)
                    ("solutionCount",    box solutions.Length)
                    ("removal_required", box removalResults)
                    ("conclusion_data",  box (List<ConclusionData>()))
                    ("steady_states",    box (List<BehaviorRecord>()))
                    ("oscillations",     box (List<BehaviorRecord>()))
                ]

                let json = JsonConvert.SerializeObject(outputObj, Formatting.None, jsonSettings())
                File.WriteAllText(outPath, json)
                use fs = new FileStream(outPath, FileMode.Open, FileAccess.Read, FileShare.Read)
                fs.Flush()
                eprintfn "Status: written %s (%d bytes, %d solutions)" (Path.GetFullPath(outPath)) (FileInfo(outPath).Length) solutions.Length
                0
            with ex ->
                let msg =
                    match ex with
                    | :? FileNotFoundException      -> sprintf "REIN load error: %s" ex.Message
                    | :? UnauthorizedAccessException -> sprintf "Access denied: %s" ex.Message
                    | :? IOException               -> sprintf "IO error: %s" ex.Message
                    | _                            -> sprintf "Error: %s" ex.Message
                eprintfn "%s" msg
                eprintfn "Stack: %s" (ex.ToString())
                writeErrorOutput outPath msg
                1

// ── FSI entry point ──────────────────────────────────────────────────────────
// fsi.CommandLineArgs.[0] is the script name; [1..] are the caller's args
let exitCode = main (fsi.CommandLineArgs |> Array.skip 1)
if exitCode <> 0 then Environment.Exit(exitCode)

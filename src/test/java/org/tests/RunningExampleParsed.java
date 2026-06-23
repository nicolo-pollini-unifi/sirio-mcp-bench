package org.tests;

import org.analysis.SystemAnalysis;
import org.analysis.SystemAnalysisBuilder;
import org.faultTree.ComponentNode;
import org.faultTree.GSPN;
import org.faultTree.StaticFaultTree;
import org.system.ComponentBasedSystem;
import org.system.FaultMode;
import org.util.ConsoleProgressMonitor;
import org.util.FaultTreeParser;
import org.util.XpnToSirioConverter;

import java.io.*;
import java.math.BigDecimal;
import java.math.MathContext;
import java.util.HashMap;
import java.util.Map;

public class RunningExampleParsed {
    private static BigDecimal maxTime = new BigDecimal("100");
    private static BigDecimal error = new BigDecimal("0.1");
    private static MathContext MC = new MathContext(10);
    private static BigDecimal bestTimeStep = BigDecimal.valueOf(1.0);

    public static void main(String[] args) throws Exception {
        String OUTPUT_DIR = "running_example";
        File directory = new File(OUTPUT_DIR);
        if (!directory.exists()) {
            directory.mkdir();
        }
        
        String caseName = "runningExampleParsed";

        Map<String, ComponentNode> dictionary = new HashMap<>();
        String failureCondition = "failure > 0";

        // PWR Components
        XpnToSirioConverter xpnToSirioConverter = new XpnToSirioConverter();
        xpnToSirioConverter.convertXPNtoPetriNet("ComponentGSPNs\\PWR_R.xpn");
        GSPN pwrGspn = new GSPN(xpnToSirioConverter.getPetriNet(), xpnToSirioConverter.getMarking());
        dictionary.put("PWR1", new ComponentNode(pwrGspn, "PWR1", failureCondition));
        dictionary.put("PWR2", new ComponentNode(pwrGspn, "PWR2", failureCondition));
        dictionary.put("PWR3", new ComponentNode(pwrGspn, "PWR3", failureCondition));

        // WAN Components
        xpnToSirioConverter = new XpnToSirioConverter();
        xpnToSirioConverter.convertXPNtoPetriNet("ComponentGSPNs\\WAN_R.xpn");
        GSPN wanGspn = new GSPN(xpnToSirioConverter.getPetriNet(), xpnToSirioConverter.getMarking());
        dictionary.put("WAN1", new ComponentNode(wanGspn, "WAN1", failureCondition));
        dictionary.put("WAN2", new ComponentNode(wanGspn, "WAN2", failureCondition));

        // GSMR Components
        xpnToSirioConverter = new XpnToSirioConverter();
        xpnToSirioConverter.convertXPNtoPetriNet("ComponentGSPNs\\GSMR_R.xpn");
        GSPN gsmrGspn = new GSPN(xpnToSirioConverter.getPetriNet(), xpnToSirioConverter.getMarking());
        dictionary.put("GSMR1", new ComponentNode(gsmrGspn, "GSMR1", failureCondition));
        dictionary.put("GSMR2", new ComponentNode(gsmrGspn, "GSMR2", failureCondition));

        // CPU Components
        xpnToSirioConverter = new XpnToSirioConverter();
        xpnToSirioConverter.convertXPNtoPetriNet("ComponentGSPNs\\CPU_R.xpn");
        GSPN cpuGspn = new GSPN(xpnToSirioConverter.getPetriNet(), xpnToSirioConverter.getMarking());
        dictionary.put("CPU1", new ComponentNode(cpuGspn, "CPU1", failureCondition));
        dictionary.put("CPU2", new ComponentNode(cpuGspn, "CPU2", failureCondition));
        dictionary.put("CPU3", new ComponentNode(cpuGspn, "CPU3", failureCondition));

        // FPGA Components
        xpnToSirioConverter = new XpnToSirioConverter();
        xpnToSirioConverter.convertXPNtoPetriNet("ComponentGSPNs\\FPGA_R.xpn");
        GSPN fpgaGspn = new GSPN(xpnToSirioConverter.getPetriNet(), xpnToSirioConverter.getMarking());
        dictionary.put("SFT1", new ComponentNode(fpgaGspn, "SFT1", failureCondition));
        dictionary.put("SFT2", new ComponentNode(fpgaGspn, "SFT2", failureCondition));

        // BUS Components
        xpnToSirioConverter = new XpnToSirioConverter();
        xpnToSirioConverter.convertXPNtoPetriNet("ComponentGSPNs\\BUS_R.xpn");
        GSPN busGspn = new GSPN(xpnToSirioConverter.getPetriNet(), xpnToSirioConverter.getMarking());
        dictionary.put("BUS1", new ComponentNode(busGspn, "BUS1", failureCondition));
        dictionary.put("BUS2", new ComponentNode(busGspn, "BUS2", failureCondition));

        String logicExpression = "(PWR1 & PWR2 & PWR3) | (WAN1 & WAN2) | (GSMR1 & GSMR2) | ( (CPU1 & CPU2 & CPU3) | (SFT1 & SFT2) ) | (BUS1 & BUS2)";
        StaticFaultTree runningExampleFaultTree = new StaticFaultTree(FaultTreeParser.parse(logicExpression, dictionary));

        ComponentBasedSystem cs = new ComponentBasedSystem();
        cs.addFaultMode(new FaultMode(runningExampleFaultTree));
        String fileSuffix = "_maxtime_" + maxTime.toPlainString() + "_step_" + bestTimeStep.toPlainString();

        ConsoleProgressMonitor.printHeader("STARTING SYSTEM ANALYSIS: " + caseName);

        SystemAnalysis sa = new SystemAnalysisBuilder(runningExampleFaultTree)
                .setError(error)
                .setMaxTime(maxTime)
                .setTimeStep(bestTimeStep)
                .setMC(MC)
                .setDebug(false)
                .build();

        long startTime = System.nanoTime();

        double steadyState;
        try (ConsoleProgressMonitor monitor = new ConsoleProgressMonitor("Steady State Analysis")) {
            steadyState = sa.computeSteadyState();
            monitor.stop("Steady State: " + steadyState);
        }

        BigDecimal[][] resultsAnalysis;
        try (ConsoleProgressMonitor monitor = new ConsoleProgressMonitor("Transient Analysis")) {
            resultsAnalysis = sa.computeTransientState();
            long endTime = System.nanoTime();
            long analysisDuration = (endTime - startTime) / 1000000;
            monitor.stop("Transient Analysis Done (" + analysisDuration + " ms)");
        }

        System.out.println("----------------------------------------------------------\n");

        writeCSV("output/" + OUTPUT_DIR + "/" + caseName + fileSuffix + "_analysis.csv", resultsAnalysis);
    }

    private static void writeCSV(String fileName, BigDecimal[][] data) {
        try (FileWriter writer = new FileWriter(fileName)) {
            for (BigDecimal[] row : data) {
                writer.write(row[0].toString() + "," + row[1].toString() + "\n");
            }
            System.out.println("CSV saved: " + fileName);
        } catch (IOException e) {
            e.printStackTrace();
        }
    }
}

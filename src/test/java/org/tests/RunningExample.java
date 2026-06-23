package org.tests;

import org.analysis.SystemAnalysis;
import org.analysis.SystemAnalysisBuilder;
import org.faultTree.ComponentNode;
import org.faultTree.GSPN;
import org.faultTree.StaticFaultTree;
import org.faultTree.gate.ANDGate;
import org.faultTree.gate.ORGate;
import org.oristool.petrinet.Marking;
import org.oristool.petrinet.PetriNet;
import org.system.ComponentBasedSystem;
import org.system.FaultMode;
import org.util.ConsoleProgressMonitor;
import org.util.XpnToSirioConverter;

import java.io.*;
import java.math.BigDecimal;
import java.math.MathContext;

public class RunningExample {
    private static BigDecimal maxTime = new BigDecimal("100");
    private static BigDecimal error = new BigDecimal("0.1");
    private static MathContext MC = new MathContext(10);
    private static BigDecimal bestTimeStep = BigDecimal.valueOf(1.0);

    public static void main(String[] args) throws Exception {
        //results output directory
        String OUTPUT_DIR = "running_example";
        File directory = new File(OUTPUT_DIR);
        if (!directory.exists()) {
            directory.mkdir();
        }
        
        String caseName = "runningExample";

        //Creating rootGate
        ORGate orGate = new ORGate("ORGate");

        ANDGate pwrANDGate = new ANDGate("pwrANDGate");
        ANDGate wanANDGate = new ANDGate("wanANDGate");
        ANDGate busANDGate = new ANDGate("busANDGate");
        ANDGate gmsrANDGate = new ANDGate("gmsrANDGate");
        ANDGate cpuANDGate = new ANDGate("cpuANDGate");
        ANDGate fpgaANDGate = new ANDGate("fpgaANDGate");
        ORGate TMRORGate = new ORGate("TMRORGate");

        //Creating component nodes and fault tree
        XpnToSirioConverter xpnToSirioConverter = new XpnToSirioConverter();
        xpnToSirioConverter.convertXPNtoPetriNet("ComponentGSPNs\\PWR_R.xpn");
        PetriNet petriNet = xpnToSirioConverter.getPetriNet();
        Marking marking = xpnToSirioConverter.getMarking();
        String failureCondition = "failure > 0";
        GSPN PWR_GSPN = new GSPN(petriNet,marking);
        ComponentNode PWR_node1 = new ComponentNode(PWR_GSPN, "PWR1", failureCondition);
        ComponentNode PWR_node2 = new ComponentNode(PWR_GSPN, "PWR2", failureCondition);
        ComponentNode PWR_node3 = new ComponentNode(PWR_GSPN, "PWR3", failureCondition);


        xpnToSirioConverter = new XpnToSirioConverter();
        xpnToSirioConverter.convertXPNtoPetriNet("ComponentGSPNs\\WAN_R.xpn");
        petriNet = xpnToSirioConverter.getPetriNet();
        marking = xpnToSirioConverter.getMarking();
        failureCondition = "failure > 0";
        GSPN WAN_GSPN = new GSPN(petriNet,marking);
        ComponentNode WAN_node1 = new ComponentNode(WAN_GSPN, "WAN1", failureCondition);
        ComponentNode WAN_node2 = new ComponentNode(WAN_GSPN, "WAN2", failureCondition);


        xpnToSirioConverter = new XpnToSirioConverter();
        xpnToSirioConverter.convertXPNtoPetriNet("ComponentGSPNs\\GSMR_R.xpn");
        petriNet = xpnToSirioConverter.getPetriNet();
        marking = xpnToSirioConverter.getMarking();
        failureCondition = "failure > 0";
        GSPN GSMR_GSPN = new GSPN(petriNet,marking);
        ComponentNode GSMR_node1 = new ComponentNode(GSMR_GSPN, "GSMR1", failureCondition);
        ComponentNode GSMR_node2 = new ComponentNode(GSMR_GSPN, "GSMR2", failureCondition);


        xpnToSirioConverter = new XpnToSirioConverter();
        xpnToSirioConverter.convertXPNtoPetriNet("ComponentGSPNs\\CPU_R.xpn");
        petriNet = xpnToSirioConverter.getPetriNet();
        marking = xpnToSirioConverter.getMarking();
        failureCondition = "failure > 0";
        GSPN CPU_GSPN = new GSPN(petriNet,marking);
        ComponentNode CPU_node1 = new ComponentNode(CPU_GSPN, "CPU1", failureCondition);
        ComponentNode CPU_node2 = new ComponentNode(CPU_GSPN, "CPU2", failureCondition);
        ComponentNode CPU_node3 = new ComponentNode(CPU_GSPN, "CPU3", failureCondition);

        xpnToSirioConverter = new XpnToSirioConverter();
        xpnToSirioConverter.convertXPNtoPetriNet("ComponentGSPNs\\FPGA_R.xpn");
        petriNet = xpnToSirioConverter.getPetriNet();
        marking = xpnToSirioConverter.getMarking();
        failureCondition = "failure > 0";
        GSPN FPGA_GSPN = new GSPN(petriNet,marking);
        ComponentNode FPGA_node1 = new ComponentNode(FPGA_GSPN, "SFT1", failureCondition);
        ComponentNode FPGA_node2 = new ComponentNode(FPGA_GSPN, "SFT2", failureCondition);

        xpnToSirioConverter = new XpnToSirioConverter();
        xpnToSirioConverter.convertXPNtoPetriNet("ComponentGSPNs\\BUS_R.xpn");
        petriNet = xpnToSirioConverter.getPetriNet();
        marking = xpnToSirioConverter.getMarking();
        failureCondition = "failure > 0";
        GSPN BUS_GSPN = new GSPN(petriNet,marking);
        ComponentNode BUS_node1 = new ComponentNode(BUS_GSPN, "BUS1", failureCondition);
        ComponentNode BUS_node2 = new ComponentNode(BUS_GSPN, "BUS2", failureCondition);

        StaticFaultTree.StaticFaultTreeBuilder pwrBuilder = new StaticFaultTree.StaticFaultTreeBuilder(pwrANDGate);
        StaticFaultTree.StaticFaultTreeBuilder wanBuilder = new StaticFaultTree.StaticFaultTreeBuilder(wanANDGate);
        StaticFaultTree.StaticFaultTreeBuilder busBuilder = new StaticFaultTree.StaticFaultTreeBuilder(busANDGate);
        StaticFaultTree.StaticFaultTreeBuilder gsmrBuilder = new StaticFaultTree.StaticFaultTreeBuilder(gmsrANDGate);
        StaticFaultTree.StaticFaultTreeBuilder cpuBuilder = new StaticFaultTree.StaticFaultTreeBuilder(cpuANDGate);
        StaticFaultTree.StaticFaultTreeBuilder fpgaBuilder = new StaticFaultTree.StaticFaultTreeBuilder(fpgaANDGate);
        StaticFaultTree.StaticFaultTreeBuilder TMRBuilder = new StaticFaultTree.StaticFaultTreeBuilder(TMRORGate);

        pwrBuilder.addNode(PWR_node1);
        pwrBuilder.addNode(PWR_node2);
        pwrBuilder.addNode(PWR_node3);
        StaticFaultTree pwrSFT = pwrBuilder.build();

        wanBuilder.addNode(WAN_node1);
        wanBuilder.addNode(WAN_node2);
        StaticFaultTree wanSFT = wanBuilder.build();

        busBuilder.addNode(BUS_node1);
        busBuilder.addNode(BUS_node2);
        StaticFaultTree busSFT = busBuilder.build();

        gsmrBuilder.addNode(GSMR_node1);
        gsmrBuilder.addNode(GSMR_node2);
        StaticFaultTree gsmrSFT = gsmrBuilder.build();

        cpuBuilder.addNode(CPU_node1);
        cpuBuilder.addNode(CPU_node2);
        cpuBuilder.addNode(CPU_node3);
        StaticFaultTree cpuSFT = cpuBuilder.build();

        fpgaBuilder.addNode(FPGA_node1);
        fpgaBuilder.addNode(FPGA_node2);
        StaticFaultTree fpgaSFT = fpgaBuilder.build();

        TMRBuilder.addFaultTree(cpuSFT);
        TMRBuilder.addFaultTree(fpgaSFT);
        StaticFaultTree tmrSFT = TMRBuilder.build();

        StaticFaultTree.StaticFaultTreeBuilder runningExampleBuilder = new StaticFaultTree.StaticFaultTreeBuilder(orGate);
        runningExampleBuilder.addFaultTree(pwrSFT);
        runningExampleBuilder.addFaultTree(wanSFT);
        runningExampleBuilder.addFaultTree(gsmrSFT);
        runningExampleBuilder.addFaultTree(tmrSFT);
        runningExampleBuilder.addFaultTree(busSFT);
        StaticFaultTree runningExampleFaultTree = runningExampleBuilder.build();

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
            for (int i = 0; i < data.length; i++) {
                writer.write(data[i][0].toString() + "," + data[i][1].toString() + "\n");
            }
            System.out.println("CSV saved: " + fileName);
        } catch (IOException e) {
            e.printStackTrace();
        }
    }
}

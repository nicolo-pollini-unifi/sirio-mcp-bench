package org.util;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import org.analysis.SystemAnalysis;
import org.analysis.SystemAnalysisBuilder;
import org.faultTree.ComponentNode;
import org.faultTree.GSPN;
import org.faultTree.StaticFaultTree;
import org.oristool.models.stpn.trees.StochasticTransitionFeature;
import org.oristool.petrinet.Marking;
import org.oristool.petrinet.PetriNet;
import org.oristool.petrinet.Transition;

import java.io.*;
import java.math.BigDecimal;
import java.math.MathContext;
import java.util.*;

/**
 * Command-line interface to execute steady-state and transient analysis
 * for a specific Fault Tree case defined in a JSON configuration file.
 */
public class SirioCLI {

    private static final String DEFAULT_XPN_PATH = "ComponentGSPNs/gilbertElliotComponent.xpn";
    private static final String FAILURE_CONDITION = "failure > 0";

    public static class ComponentConfig {
        public String type;
        public double failureRate;
        public double repairRate;
        public String xpnPath;
    }

    public static class TestCase {
        public String id;
        public String logicExpression;
        public double maxTime;
        public double timeStep;
        public double error;
        public Map<String, ComponentConfig> components;
    }

    public static class TestCasesFile {
        public long seed;
        public List<TestCase> cases;
    }

    public static class AnalysisResult {
        public String caseId;
        public double steadyState;
        public List<double[]> transientResult;
    }

    public static void main(String[] args) {
        String inputPath = null;
        String caseId = null;
        String outputPath = null;

        for (int i = 0; i < args.length; i++) {
            if ("--input".equals(args[i]) && i + 1 < args.length) {
                inputPath = args[++i];
            } else if ("--case".equals(args[i]) && i + 1 < args.length) {
                caseId = args[++i];
            } else if ("--output".equals(args[i]) && i + 1 < args.length) {
                outputPath = args[++i];
            }
        }

        if (inputPath == null || outputPath == null) {
            System.err.println("Usage: java org.util.SirioCLI --input <input_json> [--case <case_id>] --output <output_json>");
            System.exit(1);
        }

        try {
            TestCase testCase = loadTestCase(inputPath, caseId);
            if (testCase == null) {
                System.err.println("Error: TestCase not found.");
                System.exit(1);
            }

            AnalysisResult result = runAnalysis(testCase);
            saveResult(result, outputPath);
            System.out.println("Analysis completed successfully for case: " + testCase.id);

        } catch (Exception e) {
            System.err.println("Error during analysis execution: " + e.getMessage());
            e.printStackTrace();
            System.exit(1);
        }
    }

    private static TestCase loadTestCase(String inputPath, String caseId) throws IOException {
        Gson gson = new Gson();
        try (Reader reader = new FileReader(inputPath)) {
            try {
                TestCasesFile file = gson.fromJson(reader, TestCasesFile.class);
                if (file != null && file.cases != null && !file.cases.isEmpty()) {
                    if (caseId == null) {
                        return file.cases.get(0);
                    }
                    for (TestCase tc : file.cases) {
                        if (caseId.equals(tc.id)) {
                            return tc;
                        }
                    }
                }
            } catch (Exception e) {
                try (Reader r2 = new FileReader(inputPath)) {
                    return gson.fromJson(r2, TestCase.class);
                }
            }
        }
        return null;
    }

    private static AnalysisResult runAnalysis(TestCase testCase) throws Exception {
        Map<String, ComponentNode> dictionary = new HashMap<>();

        for (Map.Entry<String, ComponentConfig> entry : testCase.components.entrySet()) {
            String name = entry.getKey();
            ComponentConfig config = entry.getValue();

            String xpnPath = config.xpnPath;
            if (xpnPath == null || xpnPath.isEmpty()) {
                xpnPath = DEFAULT_XPN_PATH;
            }

            XpnToSirioConverter converter = new XpnToSirioConverter();
            converter.convertXPNtoPetriNet(xpnPath);

            PetriNet petriNet = converter.getPetriNet();
            Marking marking = converter.getMarking();

            updateTransitionRates(petriNet, config.failureRate, config.repairRate);

            GSPN gspn = new GSPN(petriNet, marking);
            ComponentNode node = new ComponentNode(gspn, name, FAILURE_CONDITION);
            dictionary.put(name, node);
        }

        StaticFaultTree faultTree = new StaticFaultTree(FaultTreeParser.parse(testCase.logicExpression, dictionary));

        MathContext mc = new MathContext(10);
        SystemAnalysis sa = new SystemAnalysisBuilder(faultTree)
                .setError(BigDecimal.valueOf(testCase.error))
                .setMaxTime(BigDecimal.valueOf(testCase.maxTime))
                .setTimeStep(BigDecimal.valueOf(testCase.timeStep))
                .setMC(mc)
                .setDebug(false)
                .build();

        double steadyState = sa.computeSteadyState();
        BigDecimal[][] transientMatrix = sa.computeTransientState();

        AnalysisResult result = new AnalysisResult();
        result.caseId = testCase.id;
        result.steadyState = steadyState;
        result.transientResult = new ArrayList<>();
        for (BigDecimal[] row : transientMatrix) {
            result.transientResult.add(new double[]{row[0].doubleValue(), row[1].doubleValue()});
        }

        return result;
    }

    private static void updateTransitionRates(PetriNet petriNet, double failureRate, double repairRate) {
        for (Transition t : petriNet.getTransitions()) {
            String name = t.getName().toLowerCase();
            if (name.equals("t0") || name.contains("fail")) {
                t.removeFeature(StochasticTransitionFeature.class);
                t.addFeature(StochasticTransitionFeature.newExponentialInstance(BigDecimal.valueOf(failureRate)));
            } else if (name.equals("t1") || name.contains("repair") || name.contains("recover")) {
                t.removeFeature(StochasticTransitionFeature.class);
                t.addFeature(StochasticTransitionFeature.newExponentialInstance(BigDecimal.valueOf(repairRate)));
            }
        }
    }

    private static void saveResult(AnalysisResult result, String outputPath) throws IOException {
        Gson gson = new GsonBuilder().setPrettyPrinting().create();
        try (Writer writer = new FileWriter(outputPath)) {
            gson.toJson(result, writer);
        }
    }
}

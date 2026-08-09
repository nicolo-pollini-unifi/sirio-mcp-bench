package org.util;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import org.faultTree.ComponentNode;
import org.faultTree.GSPN;

import java.io.FileWriter;
import java.io.IOException;
import java.util.*;

public class TestCaseGenerator {

    public enum TestTier {
        LOW,
        MEDIUM,
        HIGH
    }

    public static class TestCase {
        private final String logicExpression;
        private final Map<String, ComponentNode> dictionary;
        private final TestTier tier;

        public TestCase(String logicExpression, Map<String, ComponentNode> dictionary, TestTier tier) {
            this.logicExpression = logicExpression;
            this.dictionary = dictionary;
            this.tier = tier;
        }

        public String getLogicExpression() {
            return logicExpression;
        }

        public Map<String, ComponentNode> getDictionary() {
            return dictionary;
        }

        public TestTier getTier() {
            return tier;
        }
    }

    private static final Map<String, String> COMPONENT_FILES = new HashMap<>();

    static {
        COMPONENT_FILES.put("GE", "ComponentGSPNs/gilbertElliotComponent.xpn");
    }

    private static final String FAILURE_CONDITION = "failure > 0";

    private final Map<String, GSPN> gspnCache = new HashMap<>();
    private final long seed;
    private final Random random;

    // Separate prefix counters
    private final Map<String, Integer> prefixCounters = new HashMap<>();

    public TestCaseGenerator(long seed) {
        this.seed = seed;
        this.random = new Random(seed);
    }

    private GSPN getOrLoadGSPN(String prefix) throws Exception {
        if (gspnCache.containsKey(prefix)) {
            return gspnCache.get(prefix);
        }

        String filePath = COMPONENT_FILES.get(prefix);
        if (filePath == null) {
            throw new IllegalArgumentException("Unknown component prefix: " + prefix);
        }

        XpnToSirioConverter converter = new XpnToSirioConverter();
        converter.convertXPNtoPetriNet(filePath);

        GSPN gspn = new GSPN(converter.getPetriNet(), converter.getMarking());
        gspnCache.put(prefix, gspn);

        return gspn;
    }

    public Map<String, ComponentNode> buildDictionaryForComponents(List<String> componentNames) throws Exception {
        Map<String, ComponentNode> dictionary = new LinkedHashMap<>();

        for (String name : componentNames) {
            String prefix = name.replaceAll("\\d", "");
            GSPN gspn = getOrLoadGSPN(prefix);
            dictionary.put(name, new ComponentNode(gspn, name, FAILURE_CONDITION));
        }

        return dictionary;
    }

    private String randomPrefix(List<String> availablePrefixes) {
        return availablePrefixes.get(random.nextInt(availablePrefixes.size()));
    }

    private String nextComponentName(String prefix, List<String> usedComponents) {
        int nextId = prefixCounters.getOrDefault(prefix, 0);
        prefixCounters.put(prefix, nextId + 1);

        String nodeName = prefix + (nextId + 1); // e.g. GE1, GE2, GE3
        usedComponents.add(nodeName);

        return nodeName;
    }

    private String generateExpressionBlock(
            int depth,
            int maxDepth,
            TestTier tier,
            List<String> usedComponents,
            List<String> availablePrefixes,
            String inheritedPrefix
    ) throws Exception {

        if (depth == maxDepth) {
            String prefix = (inheritedPrefix != null)
                    ? inheritedPrefix
                    : randomPrefix(availablePrefixes);

            return nextComponentName(prefix, usedComponents);
        }

        String operatorForThisLevel = random.nextBoolean() ? " & " : " | ";

        int numSubBlocks;
        if (depth == 0) {
            numSubBlocks = random.nextInt(3) + 2; // 2-4
        } else {
            numSubBlocks = random.nextInt(2) + 2; // 2-3
        }

        List<String> subBlocks = new ArrayList<>();

        boolean homogenizeLowestGroups = (tier != TestTier.LOW);

        for (int i = 0; i < numSubBlocks; i++) {
            String childPrefix = null;

            if (homogenizeLowestGroups) {
                if (depth == maxDepth - 1) {
                    childPrefix = (inheritedPrefix != null)
                            ? inheritedPrefix
                            : randomPrefix(availablePrefixes);

                } else if (depth == maxDepth - 2) {
                    childPrefix = randomPrefix(availablePrefixes);
                }
            }

            String subBlock = generateExpressionBlock(
                    depth + 1,
                    maxDepth,
                    tier,
                    usedComponents,
                    availablePrefixes,
                    childPrefix
            );

            subBlocks.add(subBlock);
        }

        boolean useKOFN = numSubBlocks >= 3 && random.nextInt(3) == 0;
        if (useKOFN) {
            int k = random.nextInt(numSubBlocks - 1) + 1;
            if (k == 1) {
                k = 2;
            }
            if (k == numSubBlocks) {
                k--;
            }
            return "KOFN(" + k + ", " + String.join(", ", subBlocks) + ")";
        } else {
            return "(" + String.join(operatorForThisLevel, subBlocks) + ")";
        }
    }

    public TestCase generateRandomTestCase(TestTier tier) throws Exception {
        List<String> availablePrefixes = new ArrayList<>(COMPONENT_FILES.keySet());
        List<String> usedComponents = new ArrayList<>();

        prefixCounters.clear();

        int depth;
        switch (tier) {
            case LOW:
                depth = 1;
                break;
            case MEDIUM:
                depth = 2;
                break;
            case HIGH:
                depth = 3;
                break;
            default:
                depth = 1;
        }

        String logicExpression = generateExpressionBlock(
                0,
                depth,
                tier,
                usedComponents,
                availablePrefixes,
                null
        );

        Map<String, ComponentNode> dictionary = buildDictionaryForComponents(usedComponents);

        return new TestCase(logicExpression, dictionary, tier);
    }

    public void convertTestCasesToJSON(List<TestCase> testCases, TestTier tier, long seed, String outputPath) throws IOException {
        record Component (
           String type,
           float failureRate,
           float repairRate,
           String xpnPath
        ) {}

        record Case (
            String id,
            String logicExpression,
            float maxTime,
            float timeStep,
            float error,
            Map<String, Component> components
        ) {}

        record Document (
            long seed,
            String difficulty,
            int numCases,
            List<Case> cases
        ) {}

        List<Case> cases = new ArrayList<>();
        int caseIndex = 1;
        for (TestCase tCase : testCases) {
            Map<String, Component> cMap = new LinkedHashMap<>();
            for (String name : tCase.dictionary.keySet()) {
                // Reproducibly randomized rates based on the seed
                float failureRate = 5.0f + random.nextFloat() * 25.0f;
                failureRate = Math.round(failureRate * 10.0f) / 10.0f;

                float repairRate = 100.0f + random.nextFloat() * 400.0f;
                repairRate = Math.round(repairRate * 10.0f) / 10.0f;

                String xpnPath = COMPONENT_FILES.get(name.replaceAll("\\d", ""));
                Component c = new Component("gilbert-elliot", failureRate, repairRate, xpnPath);
                cMap.put(name, c);
            }

            float maxTime = 25.0f;
            float timeStep = 1.0f;
            float error = 0.1f;

            String caseId = "generated_case_" + caseIndex;
            Case tc = new Case(caseId, tCase.logicExpression, maxTime, timeStep, error, cMap);
            cases.add(tc);
            caseIndex++;
        }

        Document d = new Document(seed, tier.name(), testCases.size(), cases);

        Gson gson = new GsonBuilder().setPrettyPrinting().disableHtmlEscaping().create();
        try (FileWriter fw = new FileWriter(outputPath)) {
            gson.toJson(d, fw);
        }
    }

    public static void main(String[] args) {
        String difficultyArg = "MEDIUM";
        int numCases = 10;
        long seed = 42L;
        String outputPath = "generated_test_cases.json";

        for (int i = 0; i < args.length; i++) {
            if ("--difficulty".equals(args[i]) && i + 1 < args.length) {
                difficultyArg = args[++i].toUpperCase();
            } else if ("--numCases".equals(args[i]) && i + 1 < args.length) {
                numCases = Integer.parseInt(args[++i]);
            } else if ("--seed".equals(args[i]) && i + 1 < args.length) {
                seed = Long.parseLong(args[++i]);
            } else if ("--output".equals(args[i]) && i + 1 < args.length) {
                outputPath = args[++i];
            }
        }

        try {
            TestTier tier = TestTier.valueOf(difficultyArg);
            TestCaseGenerator generator = new TestCaseGenerator(seed);
            List<TestCase> testCases = new ArrayList<>();
            for (int i = 1; i <= numCases; i++) {
                testCases.add(generator.generateRandomTestCase(tier));
            }
            generator.convertTestCasesToJSON(testCases, tier, seed, outputPath);
            System.out.println("Generated " + numCases + " test cases for difficulty " + tier + " with seed " + seed + " in: " + outputPath);
        } catch (Exception e) {
            e.printStackTrace();
            System.exit(1);
        }
    }
}
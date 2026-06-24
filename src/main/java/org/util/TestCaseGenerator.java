package org.util;

import org.faultTree.ComponentNode;
import org.faultTree.GSPN;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Random;

public class TestCaseGenerator {

    enum TestTier {
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
        COMPONENT_FILES.put("PWR", "ComponentGSPNs\\PWR_R.xpn");
        COMPONENT_FILES.put("WAN", "ComponentGSPNs\\WAN_R.xpn");
        COMPONENT_FILES.put("GSMR", "ComponentGSPNs\\GSMR_R.xpn");
        COMPONENT_FILES.put("CPU", "ComponentGSPNs\\CPU_R.xpn");
        COMPONENT_FILES.put("SFT", "ComponentGSPNs\\FPGA_R.xpn");
        COMPONENT_FILES.put("BUS", "ComponentGSPNs\\BUS_R.xpn");
    }

    private static final String FAILURE_CONDITION = "failure > 0";

    private final Map<String, GSPN> gspnCache = new HashMap<>();
    private final Random random = new Random();

    // Contatori separati per prefisso
    private final Map<String, Integer> prefixCounters = new HashMap<>();

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

        String nodeName = prefix + String.format("%03d", nextId);
        usedComponents.add(nodeName);

        return nodeName;
    }

    /**
     * Genera ricorsivamente un blocco dell'espressione.
     *
     * inheritedPrefix:
     * - null  -> il prefisso può essere scelto liberamente
     * - value -> forza quel prefisso nel sottoalbero/foglia corrente
     */
    private String generateExpressionBlock(
            int depth,
            int maxDepth,
            TestTier tier,
            List<String> usedComponents,
            List<String> availablePrefixes,
            String inheritedPrefix
    ) throws Exception {

        // Caso componente base
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
                    // Ogni figli foglia ha lo stesso prefisso
                    childPrefix = (inheritedPrefix != null)
                            ? inheritedPrefix
                            : randomPrefix(availablePrefixes);

                } else if (depth == maxDepth - 2) {
                    // Ogni sottolivello può avere un suo prefisso, ma resta coerente al suo interno
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

        boolean useKOFN = numSubBlocks >= 3 && random.nextInt(3) == 0; // 1/3 chance di usare KOFN se ci sono almeno 3 sottoblocchi
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

        // Reset dei contatori per ogni nuovo test case
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

    public static void testGeneration() {
        try {
            TestCaseGenerator generator = new TestCaseGenerator();

            System.out.println("Generating random test cases...");
            System.out.println("=========================================");

            for (int i = 1; i <= 10; i++) {
                System.out.println("Test Case #" + i + ":");

                TestTier randTier = TestTier.values()[generator.random.nextInt(TestTier.values().length)];
                TestCase testCase = generator.generateRandomTestCase(randTier);

                System.out.println("Generated Test Case:");
                System.out.println(" - Tier: " + testCase.getTier());
                System.out.println(" - Logic Expression:");
                System.out.println("   " + testCase.getLogicExpression());
                System.out.println(" - Dictionary Keys (" + testCase.getDictionary().size() + " components):");
                System.out.print("   ");

                for (String key : testCase.getDictionary().keySet()) {
                    System.out.print(key + " ");
                }

                System.out.println("\n-----------------------------------------");
            }

        } catch (Exception e) {
            e.printStackTrace();
        }
    }

    public static void main(String[] args) {
        testGeneration();
    }
}
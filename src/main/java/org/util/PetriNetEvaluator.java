package org.util;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import org.oristool.models.gspn.GSPNSteadyState;
import org.oristool.models.gspn.GSPNTransient;
import org.oristool.models.pn.PostUpdater;
import org.oristool.models.pn.Priority;
import org.oristool.models.stpn.MarkingExpr;
import org.oristool.models.stpn.trees.StochasticTransitionFeature;
import org.oristool.petrinet.*;
import org.oristool.util.Pair;

import java.io.*;
import java.math.BigDecimal;
import java.math.MathContext;
import java.util.*;

/**
 * Utility to evaluate arbitrary Petri Nets dynamically described in a JSON format.
 * Acts as the computation engine backend for the MCP Server dummy client.
 */
public class PetriNetEvaluator {

    public static class PlaceConfig {
        public String name;
        public int tokens;
    }

    public static class TransitionConfig {
        public String name;
        public String type; // "exponential", "deterministic", "erlang"
        public double rate; // lambda or value
        public String enablingFunction;
        public String postUpdater;
        public Integer priority;
        public Integer k; // for Erlang
    }

    public static class ArcConfig {
        public String from;
        public String to;
        public String type; // "precondition" or "postcondition"
    }

    public static class AnalysisConfig {
        public String type; // "transient", "steady", "both"
        public double maxTime;
        public double timeStep;
        public double error;
        public String failureCondition;
    }

    public static class PetriNetConfig {
        public List<PlaceConfig> places;
        public List<TransitionConfig> transitions;
        public List<ArcConfig> arcs;
        public AnalysisConfig analysis;
    }

    public static class EvaluatorResult {
        public double steadyState = -1.0;
        public List<double[]> transientResult;
        public String error;
    }

    public static void main(String[] args) {
        String inputPath = null;
        String outputPath = null;

        for (int i = 0; i < args.length; i++) {
            if ("--input".equals(args[i]) && i + 1 < args.length) {
                inputPath = args[++i];
            } else if ("--output".equals(args[i]) && i + 1 < args.length) {
                outputPath = args[++i];
            }
        }

        if (inputPath == null || outputPath == null) {
            System.err.println("Usage: java org.util.PetriNetEvaluator --input <input_json> --output <output_json>");
            System.exit(1);
        }

        EvaluatorResult result = new EvaluatorResult();
        try {
            Gson gson = new Gson();
            PetriNetConfig config;
            try (Reader reader = new FileReader(inputPath)) {
                config = gson.fromJson(reader, PetriNetConfig.class);
            }

            if (config == null) {
                throw new IllegalArgumentException("Failed to parse PetriNetConfig from input JSON.");
            }

            evaluatePetriNet(config, result);

        } catch (Exception e) {
            result.error = e.getMessage();
            System.err.println("Evaluation error: " + e.getMessage());
            e.printStackTrace();
        }

        try {
            Gson gson = new GsonBuilder().setPrettyPrinting().create();
            try (Writer writer = new FileWriter(outputPath)) {
                gson.toJson(result, writer);
            }
        } catch (IOException e) {
            System.err.println("Failed to write output JSON: " + e.getMessage());
        }
    }

    private static void evaluatePetriNet(PetriNetConfig config, EvaluatorResult result) throws Exception {
        PetriNet petriNet = new PetriNet();
        Marking marking = new Marking();

        Map<String, Place> placesMap = new HashMap<>();
        Map<String, Transition> transitionsMap = new HashMap<>();

        // 1. Add Places
        if (config.places != null) {
            for (PlaceConfig pConfig : config.places) {
                Place place = petriNet.addPlace(pConfig.name);
                placesMap.put(pConfig.name, place);
                if (pConfig.tokens > 0) {
                    marking.setTokens(place, pConfig.tokens);
                }
            }
        }

        // 2. Add Transitions
        if (config.transitions != null) {
            for (TransitionConfig tConfig : config.transitions) {
                Transition transition = petriNet.addTransition(tConfig.name);
                transitionsMap.put(tConfig.name, transition);

                // Add stochastic feature
                String type = tConfig.type != null ? tConfig.type.toLowerCase() : "exponential";
                if ("deterministic".equals(type)) {
                    transition.addFeature(StochasticTransitionFeature.newDeterministicInstance(BigDecimal.valueOf(tConfig.rate)));
                } else if ("erlang".equals(type)) {
                    int k = tConfig.k != null ? tConfig.k : 1;
                    transition.addFeature(StochasticTransitionFeature.newErlangInstance(k, BigDecimal.valueOf(tConfig.rate)));
                } else {
                    // Default to exponential
                    transition.addFeature(StochasticTransitionFeature.newExponentialInstance(BigDecimal.valueOf(tConfig.rate)));
                }

                // Optional priority
                if (tConfig.priority != null) {
                    transition.addFeature(new Priority(tConfig.priority));
                }

                // Optional enabling function
                if (tConfig.enablingFunction != null && !tConfig.enablingFunction.isEmpty()) {
                    transition.addFeature(new EnablingFunction(tConfig.enablingFunction));
                }

                // Optional post updater
                if (tConfig.postUpdater != null && !tConfig.postUpdater.isEmpty()) {
                    transition.addFeature(new PostUpdater(tConfig.postUpdater, petriNet));
                }
            }
        }

        // 3. Add Arcs
        if (config.arcs != null) {
            for (ArcConfig aConfig : config.arcs) {
                String from = aConfig.from;
                String to = aConfig.to;
                String type = aConfig.type != null ? aConfig.type.toLowerCase() : "";

                if ("precondition".equals(type) || (placesMap.containsKey(from) && transitionsMap.containsKey(to))) {
                    Place p = placesMap.get(from);
                    Transition t = transitionsMap.get(to);
                    if (p == null || t == null) {
                        throw new IllegalArgumentException("Invalid arc from '" + from + "' to '" + to + "'");
                    }
                    petriNet.addPrecondition(p, t);
                } else if ("postcondition".equals(type) || (transitionsMap.containsKey(from) && placesMap.containsKey(to))) {
                    Transition t = transitionsMap.get(from);
                    Place p = placesMap.get(to);
                    if (t == null || p == null) {
                        throw new IllegalArgumentException("Invalid arc from '" + from + "' to '" + to + "'");
                    }
                    petriNet.addPostcondition(t, p);
                } else {
                    throw new IllegalArgumentException("Cannot infer arc direction for from '" + from + "' to '" + to + "'");
                }
            }
        }

        AnalysisConfig analysis = config.analysis;
        if (analysis == null) {
            throw new IllegalArgumentException("Analysis config is missing.");
        }

        String analysisType = analysis.type != null ? analysis.type.toLowerCase() : "both";
        MarkingExpr markingExpr = MarkingExpr.from(analysis.failureCondition, petriNet);

        // 4. Run Steady State Analysis
        if ("steady".equals(analysisType) || "both".equals(analysisType)) {
            Map<Marking, Double> ssResult = GSPNSteadyState.builder().build().compute(petriNet, marking);
            double steadyStateProb = 0.0;
            boolean found = false;

            for (Map.Entry<Marking, Double> entry : ssResult.entrySet()) {
                if (markingExpr.evaluate(entry.getKey()) > 0) {
                    steadyStateProb += entry.getValue();
                    found = true;
                }
            }
            if (found) {
                result.steadyState = steadyStateProb;
            } else {
                result.steadyState = 0.0;
            }
        }

        // 5. Run Transient Analysis
        if ("transient".equals(analysisType) || "both".equals(analysisType)) {
            double startTime = 0.0;
            double endTime = analysis.maxTime;
            double step = analysis.timeStep;

            Pair<Map<Marking, Integer>, double[][]> transResult = GSPNTransient.builder()
                    .timePoints(startTime, endTime, step)
                    .build().compute(petriNet, marking);

            Map<Marking, Integer> statePos = transResult.first();
            double[][] probs = transResult.second();
            int nSteps = probs.length;

            BigDecimal[] failureSolution = new BigDecimal[nSteps];
            for (int i = 0; i < nSteps; i++) {
                failureSolution[i] = BigDecimal.ZERO;
            }

            boolean foundFailureMarking = false;
            for (Map.Entry<Marking, Integer> entry : statePos.entrySet()) {
                if (markingExpr.evaluate(entry.getKey()) > 0) {
                    int markingPos = entry.getValue();
                    for (int t = 0; t < nSteps; t++) {
                        failureSolution[t] = failureSolution[t].add(BigDecimal.valueOf(probs[t][markingPos]));
                    }
                    foundFailureMarking = true;
                }
            }

            MathContext mc = new MathContext(10);
            result.transientResult = new ArrayList<>();
            for (int i = 0; i < nSteps; i++) {
                double time = step * i;
                double prob = foundFailureMarking ? failureSolution[i].doubleValue() : 0.0;
                result.transientResult.add(new double[]{time, prob});
            }
        }
    }
}

package org.util;

import ch.obermuhlner.math.big.BigDecimalMath;
import com.google.common.graph.MutableValueGraph;
import org.faultTree.ComponentNode;
import org.faultTree.StaticFaultTree;
import org.oristool.models.gspn.GSPNTransient;
import org.oristool.models.gspn.chains.DTMC;
import org.oristool.models.gspn.reachability.GSPNReachability;
import org.oristool.models.gspn.reachability.SPNState;
import org.oristool.models.stpn.MarkingExpr;
import org.oristool.petrinet.Marking;
import org.oristool.petrinet.PetriNet;
import org.oristool.util.Pair;

import java.math.BigDecimal;
import java.math.BigInteger;
import java.math.MathContext;
import java.math.RoundingMode;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

public class TimeStepFinder {

    public static BigDecimal selectBestTimestep(StaticFaultTree faultTree, BigDecimal maxTime, double epsilon) {
        MathContext MC = new MathContext(30);
        BigDecimal eps = BigDecimal.valueOf(epsilon);

        //Calculate deltaTLambda
        BigDecimal numerator = eps.multiply(BigDecimal.valueOf(2));
        BigDecimal denominator = BigDecimal.ZERO;
        for(ComponentNode component : faultTree.getAllNodes()){
            BigDecimal lambda_i = calculateMaxLambda(faultTree,maxTime,component);
            denominator = denominator.add(lambda_i);
        }
        BigDecimal deltaTLambda = numerator.divide(denominator,MC);

        //Calculating deltaTMu
        BigDecimal delta = BigDecimal.ONE.subtract(BigDecimal.valueOf(epsilon));
        BigDecimal ln_delta = BigDecimalMath.log(delta,MC);
        numerator = ln_delta.negate();
        denominator = calculateMinMu(faultTree,maxTime);
        BigDecimal deltaTMu = numerator.divide(denominator,MC);

        BigDecimal minTimestep = deltaTLambda;
        if(deltaTLambda.compareTo(deltaTMu) > 0){
            minTimestep =  deltaTMu;
        }

        BigDecimal quotient = maxTime.divide(minTimestep, 0, RoundingMode.CEILING); // no fractional part
        BigInteger N = quotient.toBigIntegerExact();

        // h = T / N
        BigDecimal bestDeltaT = maxTime.divide(new BigDecimal(N), MC);
        BigDecimal threshold = maxTime;
        if(bestDeltaT.compareTo(threshold) <= 0){
            return bestDeltaT;
        }else{
            return threshold;
        }
    }

    private static BigDecimal calculateMaxLambda(StaticFaultTree staticFaultTree, BigDecimal maxTime, ComponentNode componentNode) {
        List<BigDecimal> lambdas = new ArrayList<>();
        PetriNet componentNode_pn = componentNode.getComponentGSPN().getPetriNet();
        Marking componentNode_marking = componentNode.getComponentGSPN().getMarking();

        DTMC<SPNState> gspnGraph = GSPNReachability.builder().build().compute(componentNode_pn, componentNode_marking);
        MutableValueGraph<SPNState, Double> probgraph = gspnGraph.probsGraph();
        Set<SPNState> states = probgraph.nodes();

        MarkingExpr markingExpr = MarkingExpr.from(componentNode.getFailureCondition(), componentNode_pn);

        Pair<Map<Marking, Integer>, double[][]> result = GSPNTransient.builder()
                .timePoints(0, maxTime.doubleValue(), 0.01)
                .build().compute(componentNode_pn, componentNode_marking);

        Map<Marking, Integer> statePos = result.first();
        List<Marking> failureMarkings = new ArrayList<>();
        for (Marking m : statePos.keySet()) {
            if (markingExpr.evaluate(m) > 0) {
                failureMarkings.add(m);
            }
        }

        List<SPNState> failureStates = states.stream()
                .filter(state -> failureMarkings.contains(state.state()))
                .toList();

        Map<SPNState, Map<SPNState, Double>> stateMatrix = computeStateMatrix(staticFaultTree, componentNode, probgraph, states);

        List<Double> maxRates = stateMatrix.entrySet().stream()
                // solo stati NON failure
                .filter(entry -> !failureStates.contains(entry.getKey()))
                // per ciascuno, massimo rate verso stati di failure
                .map(entry -> entry.getValue().entrySet().stream()
                        .filter(e -> failureStates.contains(e.getKey())) // solo transizioni verso failure
                        .map(Map.Entry::getValue)                        // prendiamo il valore del rate
                        .max(Double::compareTo)                          // massimo, se esiste
                        .orElse(0.0))                              // se nessuna transizione, 0
                .toList();

        return BigDecimal.valueOf(Collections.max(maxRates));
    }

    private static BigDecimal calculateMinMu(StaticFaultTree staticFaultTree, BigDecimal maxTime) {
        List<BigDecimal> mus = new ArrayList<>();
        for(ComponentNode componentNode : staticFaultTree.getAllNodes()){
            PetriNet componentNode_pn = componentNode.getComponentGSPN().getPetriNet();
            Marking componentNode_marking = componentNode.getComponentGSPN().getMarking();

            DTMC<SPNState> gspnGraph = GSPNReachability.builder().build().compute(componentNode_pn, componentNode_marking);
            MutableValueGraph<SPNState, Double> probgraph = gspnGraph.probsGraph();
            Set<SPNState> states = probgraph.nodes();

            MarkingExpr markingExpr = MarkingExpr.from(componentNode.getFailureCondition(), componentNode_pn);

            Pair<Map<Marking, Integer>, double[][]> result = GSPNTransient.builder()
                    .timePoints(0, maxTime.doubleValue(), 0.01)
                    .build().compute(componentNode_pn, componentNode_marking);

            Map<Marking, Integer> statePos = result.first();
            List<Marking> failureMarkings = new ArrayList<>();
            for (Marking m : statePos.keySet()) {
                if (markingExpr.evaluate(m)> 0) {
                    failureMarkings.add(m);
                }
            }

            List<SPNState> failureStates = states.stream()
                    .filter(state -> failureMarkings.contains(state.state()))
                    .toList();

            Map<SPNState, Map<SPNState, Double>> stateMatrix = computeStateMatrix(staticFaultTree,componentNode, probgraph,states);

            OptionalDouble component_minMu = failureStates.parallelStream().mapToDouble(state -> {
                Map<SPNState, Double> successors = stateMatrix.get(state);
                return Collections.max(successors.values());
            }).min();

            if(component_minMu.isEmpty()){
                throw new IllegalStateException("max mu of component " + componentNode.getName() + " is empty.");
            }

            mus.add(BigDecimal.valueOf(component_minMu.getAsDouble()));
        }

        BigDecimal minMu = BigDecimal.valueOf(Double.MAX_VALUE);
        for (BigDecimal mu : mus){
            if(minMu.compareTo(mu) >= 0){
                minMu = mu;
            }
        }
        return minMu;
    }

    private static Map<SPNState, Map<SPNState, Double>> computeStateMatrix(StaticFaultTree faultTree,ComponentNode componentNode, MutableValueGraph<SPNState, Double> probgraph, Set<SPNState> states){
        Map<SPNState, Map<SPNState, Double>> stateMatrix = new ConcurrentHashMap<>();
        states.parallelStream().forEach(state -> {
            Map<SPNState, Double> transitions = new HashMap<>();
            for (SPNState succ : probgraph.successors(state)) {
                if (!state.equals(succ)) {
                    double edgeProb = probgraph.edgeValueOrDefault(state, succ, 0.0);
                    if (edgeProb > 0.0) {
                        double exitRate = state.exitRate();
                        double rate = edgeProb * exitRate;
                        transitions.put(succ, rate);
                    }
                }
            }
            stateMatrix.put(state, transitions);
        });
        return stateMatrix;
    }

}

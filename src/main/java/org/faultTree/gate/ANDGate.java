package org.faultTree.gate;

import org.faultTree.ComponentNode;

import java.util.*;
import java.util.stream.Stream;

public class ANDGate extends Gate{

    public ANDGate(String identifier, List<Gate> gates,List<ComponentNode> nodes) {
        super(identifier,gates,nodes);
    }

    public ANDGate(String identifier){
        super(identifier);
    }

//    @Override
//    public Set<Set<ComponentNode>> getMinCutSets() {
//        if (minCutSetsCache != null) {
//            return minCutSetsCache;
//        }
//
//        Set<Set<ComponentNode>> result = new HashSet<>();
//        for(ComponentNode node: nodes){
//            if(result.isEmpty()){
//                Set<ComponentNode> exploredNode = Collections.singleton(node);
//                result.add(exploredNode);
//            }else{
//                Set<Set<ComponentNode>> newResult = new HashSet<>();
//                for(Set<ComponentNode> existingSet : result){
//                    Set<ComponentNode> combinedSet = new HashSet<>(existingSet);
//                    combinedSet.add(node);
//                    newResult.add(combinedSet);
//                }
//                result = newResult;
//            }
//        }
//
//        for(Gate gate: gates){
//            Set<Set<ComponentNode>> gateMCS = gate.getMinCutSets();
//            if(result.isEmpty()){
//                result.addAll(gateMCS);
//            }else{
//                Set<Set<ComponentNode>> newResult = new HashSet<>();
//                for (Set<ComponentNode> existingSet : result) {
//                    for (Set<ComponentNode> newSet : gateMCS) {
//                        Set<ComponentNode> combinedSet = new HashSet<>(existingSet);
//                        combinedSet.addAll(newSet);
//                        newResult.add(combinedSet);
//                    }
//                }
//                result = newResult;
//            }
//        }
//
//        minCutSetsCache = filterMinCutSets(result);
//        return minCutSetsCache;
//    }

    @Override
    public synchronized Set<Set<ComponentNode>> getMinCutSets() {
        if (minCutSetsCache != null) {
            return minCutSetsCache;
        }

        Set<Set<ComponentNode>> result = new HashSet<>();

        // Process nodes
        for (ComponentNode node : nodes) {
            if (result.isEmpty()) {
                result.add(Collections.singleton(node));
            } else {
                Set<Set<ComponentNode>> newResult = new HashSet<>();
                for (Set<ComponentNode> existingSet : result) {
                    Set<ComponentNode> combinedSet = new HashSet<>(existingSet);
                    combinedSet.add(node);
                    if (combinedSet.size() <= MAX_ORDER) {
                        newResult.add(combinedSet);
                    }
                }
                result = newResult;
            }
        }

        // Compute sub-gate MCSs in parallel
        Stream<Gate> gateStream = PARALLEL ? gates.parallelStream() : gates.stream();
        List<Set<Set<ComponentNode>>> gateMCSs = gateStream
                .map(Gate::getMinCutSets)
                .toList();

        // Combine AND logic
        for (Set<Set<ComponentNode>> gateMCS : gateMCSs) {
            if (result.isEmpty()) {
                result.addAll(gateMCS);
            } else {
                Set<Set<ComponentNode>> newResult = new HashSet<>();
                for (Set<ComponentNode> existingSet : result) {
                    for (Set<ComponentNode> newSet : gateMCS) {
                        Set<ComponentNode> combinedSet = new HashSet<>(existingSet);
                        combinedSet.addAll(newSet);
                        if (combinedSet.size() <= MAX_ORDER) {
                            newResult.add(combinedSet);
                        }
                    }
                }
                result = newResult;
            }

            result = filterMinCutSets(result);
        }

        // cache result
        minCutSetsCache = filterMinCutSets(result);
        return minCutSetsCache;
    }

    public synchronized Set<Set<ComponentNode>> getMinCutSetsTotal() {
        Set<Set<ComponentNode>> result = new HashSet<>();

        // Process nodes
        for (ComponentNode node : nodes) {
            if (result.isEmpty()) {
                result.add(Collections.singleton(node));
            } else {
                Set<Set<ComponentNode>> newResult = new HashSet<>();
                for (Set<ComponentNode> existingSet : result) {
                    Set<ComponentNode> combinedSet = new HashSet<>(existingSet);
                    combinedSet.add(node);
                    newResult.add(combinedSet);
                }
                result = newResult;
            }
        }

        // Compute sub-gate MCSs in parallel
        Stream<Gate> gateStream = PARALLEL ? gates.parallelStream() : gates.stream();
        List<Set<Set<ComponentNode>>> gateMCSs = gateStream
                .map(Gate::getMinCutSetsTotal)
                .toList();

        // Combine AND logic
        for (Set<Set<ComponentNode>> gateMCS : gateMCSs) {
            if (result.isEmpty()) {
                result.addAll(gateMCS);
            } else {
                Set<Set<ComponentNode>> newResult = new HashSet<>();
                for (Set<ComponentNode> existingSet : result) {
                    for (Set<ComponentNode> newSet : gateMCS) {
                        Set<ComponentNode> combinedSet = new HashSet<>(existingSet);
                        combinedSet.addAll(newSet);
                        newResult.add(combinedSet);
                    }
                }
                result = newResult;
            }

            result = filterMinCutSets(result);
        }

        // cache result
        minCutSetsCache = filterMinCutSets(result);
        return minCutSetsCache;
    }

    @Override
    public Gate copy() {
        Gate copyGate = new ANDGate(this.identifier);
        for(Gate gate: gates){
            Gate newGate = gate.copy();
            copyGate.addGate(newGate);
        }
        for(ComponentNode node: nodes){
            ComponentNode newNode = new ComponentNode(node);
            copyGate.addNode(newNode);
        }
        return copyGate;
    }

//    private Set<Set<ComponentNode>> filterMinCutSets(Set<Set<ComponentNode>> cutSets) {
//        Set<Set<ComponentNode>> minCutSets = new HashSet<>(cutSets);
//        for (Set<ComponentNode> cutSet : cutSets) {
//            for (Set<ComponentNode> potentialSubset : cutSets) {
//                if (!cutSet.equals(potentialSubset) && cutSet.containsAll(potentialSubset)) {
//                    minCutSets.remove(cutSet);
//                    break;
//                }
//            }
//        }
//        return minCutSets;
//    }

    private Set<Set<ComponentNode>> filterMinCutSets(Set<Set<ComponentNode>> cutSets) {
        List<Set<ComponentNode>> sorted = new ArrayList<>(cutSets);
        sorted.sort(Comparator.comparingInt(Set::size));

        Set<Set<ComponentNode>> minCutSets = new HashSet<>();
        for (Set<ComponentNode> candidate : sorted) {
            boolean isMinimal = minCutSets.stream().noneMatch(candidate::containsAll);
            if (isMinimal) {
                minCutSets.add(candidate);
            }
        }
        return minCutSets;
    }

    @Override
    public double estimateLogMCS() {
        double log = 0;

        for (Gate g : gates) {
            log += g.estimateLogMCS();
        }

        if (!nodes.isEmpty()) {
            log += Math.log10(nodes.size());
        }

        return log;
    }

}

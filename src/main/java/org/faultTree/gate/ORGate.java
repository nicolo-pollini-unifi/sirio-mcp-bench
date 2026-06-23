package org.faultTree.gate;

import org.faultTree.ComponentNode;

import java.util.*;
import java.util.stream.Stream;



public class ORGate extends Gate{

    public ORGate(String identifier) {
        super(identifier);
    }

    public ORGate(String identifier,List<Gate> gates, List<ComponentNode> nodes){
        super(identifier, gates, nodes);
    }

    @Override
    public synchronized Set<Set<ComponentNode>> getMinCutSets() {
        if (minCutSetsCache != null) {
            return minCutSetsCache;
        }

        Set<Set<ComponentNode>> result = new HashSet<>();

        // Add direct component nodes
        for (ComponentNode node : nodes) {
            result.add(Collections.singleton(node));
        }

        // Collect sub-gate MCSs (in parallel if desired)
        Stream<Gate> gateStream = PARALLEL ? gates.parallelStream() : gates.stream();
        List<Set<Set<ComponentNode>>> gateMCSs = gateStream
                .map(Gate::getMinCutSets)
                .toList();

        // Merge (OR = union)
        for (Set<Set<ComponentNode>> gateMCS : gateMCSs) {
            result.addAll(gateMCS);

            // prune incrementally to keep memory low
            result = filterMinCutSets(result);
        }

        // Cache and return
        minCutSetsCache = filterMinCutSets(result);
        return minCutSetsCache;
    }


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

    public Gate copy() {
        Gate copyGate = new ORGate(this.identifier);
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

    @Override
    public double estimateLogMCS() {
        double sum = nodes.size();

        for (Gate g : gates) {
            sum += Math.pow(10, g.estimateLogMCS());
        }

        if (sum == 0) return 0;
        return Math.log10(sum);
    }

    @Override
    public Set<Set<ComponentNode>> getMinCutSetsTotal() {
        Set<Set<ComponentNode>> result = new HashSet<>();

        // Add direct component nodes
        for (ComponentNode node : nodes) {
            result.add(Collections.singleton(node));
        }

        // Collect sub-gate MCSs (in parallel if desired)
        Stream<Gate> gateStream = PARALLEL ? gates.parallelStream() : gates.stream();
        List<Set<Set<ComponentNode>>> gateMCSs = gateStream
                .map(Gate::getMinCutSetsTotal)
                .toList();

        // Merge (OR = union)
        for (Set<Set<ComponentNode>> gateMCS : gateMCSs) {
            result.addAll(gateMCS);

            // prune incrementally to keep memory low
            result = filterMinCutSets(result);
        }

        // Cache and return
        minCutSetsCache = filterMinCutSets(result);
        return minCutSetsCache;
    }
}

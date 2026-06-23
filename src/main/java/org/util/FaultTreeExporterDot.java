package org.util;

import org.faultTree.ComponentNode;
import org.faultTree.StaticFaultTree;
import org.faultTree.gate.ANDGate;
import org.faultTree.gate.Gate;
import org.faultTree.gate.KofNGate;
import org.faultTree.gate.ORGate;
import org.oristool.models.pn.PostUpdater;
import org.oristool.models.pn.Priority;
import org.oristool.models.stpn.trees.StochasticTransitionFeature;
import org.oristool.petrinet.*;

import java.io.BufferedWriter;
import java.io.FileWriter;
import java.io.IOException;
import java.math.BigDecimal;
import java.util.*;

public class FaultTreeExporterDot {

    public static void exportToDot(StaticFaultTree tree, String filename) throws IOException {
        try (BufferedWriter writer = new BufferedWriter(new FileWriter(filename))) {
            writer.write("digraph FaultTree {\n");
            writer.write("  rankdir=TB;\n");
            writer.write("  node [fontname=\"Helvetica\"];\n\n");

            Set<ComponentNode> visited = new HashSet<>();
            Set<Gate> gateVisited = new HashSet<>();
            Gate rootGate = tree.getRootGate();
            writeRecursive(writer, rootGate, visited, gateVisited);

            writer.write("}\n");
        }
    }

    private static void writeRecursive(BufferedWriter writer, Gate rootGate, Set<ComponentNode> visited, Set<Gate> gateVisited) throws IOException {
        if (rootGate == null || gateVisited.contains(rootGate)) {
            return;
        }

        String rootLabel = rootGate.getIdentifier();
        String shape = "box";
        String color = "lightblue";
        writer.write(String.format("  \"%s\" [label=\"%s\", shape=%s, style=filled, fillcolor=%s];\n",
                rootLabel, rootLabel, shape, color));
        gateVisited.add(rootGate);

        for(ComponentNode node : rootGate.getNodes()) {
            String label = node.getName();
            shape = "ellipse";
            color = "lightgrey";
            writer.write(String.format("  \"%s\" [label=\"%s\", shape=%s, style=filled, fillcolor=%s];\n", label, label, shape, color));
            writer.write(String.format("  \"%s\" -> \"%s\";\n", rootLabel, label));
        }

        for(Gate gate : rootGate.getGates()) {
            String label = gate.getIdentifier();
            shape = "box";
            color = "lightblue";
            writer.write(String.format("  \"%s\" [label=\"%s\", shape=%s, style=filled, fillcolor=%s];\n", label, label, shape, color));
            writer.write(String.format("  \"%s\" -> \"%s\";\n", rootLabel, label));
            if(!gateVisited.contains(gate)){
                writeRecursive(writer, gate, visited, gateVisited);
            }
        }
    }

    public static void exportPetriNetToDot(StaticFaultTree tree, String filename) throws IOException {
        try (BufferedWriter writer = new BufferedWriter(new FileWriter(filename))) {
            writer.write("digraph PetriNet{\n");
            writer.write("  rankdir=TB;\n");
            writer.write("  node [fontname=\"Helvetica\"];\n\n");


            PetriNet systemPetriNet = new PetriNet();
            Marking systemMarking = new Marking();
            HashMap<String, String> components = new HashMap<>();
            processFaultTree(tree,systemPetriNet,systemMarking,components);

            for(Place place : systemPetriNet.getPlaces()){
                String label = place.getName();
                String shape = "ellipsis";
                String color = "lightgrey";
                writer.write(String.format("  \"%s\" [label=\"%s\", shape=%s, style=filled, fillcolor=%s];\n", label, label, shape, color));
            }

            for(Transition transition : systemPetriNet.getTransitions()){
                String transitionLabel = transition.getName();
                String transitionShape = "box";
                String transitionColor = "lightblue";
                writer.write(String.format("  \"%s\" [label=\"%s\", shape=%s, style=filled, fillcolor=%s];\n", transitionLabel, transitionLabel, transitionShape, transitionColor));

                for(Precondition precondition: systemPetriNet.getPreconditions(transition)){
                    String placeLabel = precondition.getPlace().getName();
                    writer.write(String.format("  \"%s\" -> \"%s\";\n", placeLabel, transitionLabel));
                }

                for(Postcondition postcondition : systemPetriNet.getPostconditions(transition)){
                    String placeLabel = postcondition.getPlace().getName();
                    writer.write(String.format("  \"%s\" -> \"%s\";\n",transitionLabel,placeLabel ));
                }
            }
            writer.write("}\n");
        }
    }

    private static String processFaultTree(StaticFaultTree faultTree,PetriNet systemPetriNet, Marking systemMarking, HashMap<String,String> components) {
        Gate rootGate = faultTree.getRootGate();
        return processGate(systemPetriNet,systemMarking,components, rootGate, true) + ">0";
    }

    private static String processGate(PetriNet systemPetriNet, Marking systemMarking, HashMap<String,String> components, Gate gate, boolean root){
        if(gate instanceof ANDGate){
            return processANDGate(systemPetriNet, systemMarking,components, (ANDGate)gate, root);
        }else if(gate instanceof ORGate){
            return processORGate(systemPetriNet,systemMarking, components,(ORGate)gate, root);
        }else if (gate instanceof KofNGate){
            return processKofNGate(systemPetriNet,systemMarking, components, (KofNGate)gate, root);
        }
        throw new IllegalStateException("Unsupported GATE type");
    }

    private static String processANDGate(PetriNet systemPetriNet, Marking systemMarking, HashMap<String,String> components,  ANDGate gate, boolean root) {
        List<String> gateFailurePlaces = new ArrayList<>();
        for(Gate entrygate : gate.getGates()){
            String failurePlace = processGate(systemPetriNet,systemMarking,components,entrygate, false);
            gateFailurePlaces.add(failurePlace);
        }

        Set<String> nodeFailurePlaces = new HashSet<>();
        for(ComponentNode node : gate.getNodes()){
            String nodeFailurePlace = createComponentPetriNetCopy(components, systemPetriNet, systemMarking, node);
            nodeFailurePlaces.add(nodeFailurePlace);
        }

        Place failurePlace = systemPetriNet.addPlace(gate.getIdentifier() + "_ANDfailure");
        Transition failureTransition = systemPetriNet.addTransition(gate.getIdentifier()+ "_failTrans");
        failureTransition.addFeature(StochasticTransitionFeature.newDeterministicInstance(BigDecimal.ZERO));
        failureTransition.addFeature(new Priority(41));
        StringBuilder transitionConditionBuilder = new StringBuilder();
        for(String gateFailurePlace : gateFailurePlaces){
            transitionConditionBuilder.append("*");
            if(transitionConditionBuilder.toString().equals("*")){
                transitionConditionBuilder = new StringBuilder(gateFailurePlace + "*");
            }
            transitionConditionBuilder.append(gateFailurePlace);
        }
        for(String nodeFailurePlace : nodeFailurePlaces){
            transitionConditionBuilder.append("*");
            if(transitionConditionBuilder.toString().equals("*")){
                transitionConditionBuilder = new StringBuilder(nodeFailurePlace+ "*");
            }
            transitionConditionBuilder.append(nodeFailurePlace);
        }
        String gateFailTransitionCondition = transitionConditionBuilder.toString();
        gateFailTransitionCondition = gateFailTransitionCondition + " > 0 && " + failurePlace + " == 0";
        failureTransition.addFeature(new EnablingFunction(gateFailTransitionCondition));
        if(root) {
            StringBuilder markingUpdateStringBuilder = new StringBuilder();
            Collection<Place> places = systemPetriNet.getPlaces();
            for(Place place : places){
                if(!place.equals(failurePlace)){
                    markingUpdateStringBuilder.append(place.getName()).append(" = 0 ;");
                }
            }
            String markingUpdateString = markingUpdateStringBuilder.toString();
            failureTransition.addFeature(new PostUpdater(markingUpdateString, systemPetriNet));
        }
        systemPetriNet.addPostcondition(failureTransition,failurePlace);

        transitionConditionBuilder.append(" < 1");
        String resetCondition = transitionConditionBuilder.toString();
        if(!root){
            Transition resetTransition = systemPetriNet.addTransition(gate.getIdentifier()+ "_resetTrans");
            resetTransition.addFeature(StochasticTransitionFeature.newDeterministicInstance(BigDecimal.ZERO));
            resetTransition.addFeature(new Priority(42));
            resetTransition.addFeature(new EnablingFunction(resetCondition));
            systemPetriNet.addPrecondition(failurePlace,resetTransition);
        }
        return failurePlace.getName();
    }

    private static String processORGate(PetriNet systemPetriNet, Marking systemMarking, HashMap<String,String> components, ORGate gate, boolean root) {
        List<String> gateFailurePlaces = new ArrayList<>();
        for(Gate entrygate : gate.getGates()){
            String failurePlace = processGate(systemPetriNet,systemMarking,components,entrygate, false);
            gateFailurePlaces.add(failurePlace);
        }

        Set<String> nodeFailurePlaces = new HashSet<>();
        for(ComponentNode node : gate.getNodes()){
            String nodeFailurePlace = createComponentPetriNetCopy(components,systemPetriNet, systemMarking, node);
            nodeFailurePlaces.add(nodeFailurePlace);
        }

        Place failurePlace = systemPetriNet.addPlace(gate.getIdentifier() + "_ORfailure");
        Transition failureTransition = systemPetriNet.addTransition(gate.getIdentifier() + "_failTrans");
        failureTransition.addFeature(StochasticTransitionFeature.newDeterministicInstance(BigDecimal.ZERO));
        failureTransition.addFeature(new Priority(41));
        StringBuilder resetConditionBuilder = new StringBuilder();
        for(String gateFailurePlace : gateFailurePlaces){
            resetConditionBuilder.append("+");
            if(resetConditionBuilder.toString().equals("+")){
                resetConditionBuilder = new StringBuilder(gateFailurePlace + "+");
            }
            resetConditionBuilder.append(gateFailurePlace);
        }
        for(String nodeFailurePlace : nodeFailurePlaces){
            resetConditionBuilder.append("+");
            if(resetConditionBuilder.toString().equals("+")){
                resetConditionBuilder = new StringBuilder(nodeFailurePlace + "+");
            }
            resetConditionBuilder.append(nodeFailurePlace);
        }
        String gateFailTransitionCondition = resetConditionBuilder.toString();
        gateFailTransitionCondition = gateFailTransitionCondition + " > 0 && " + failurePlace + " == 0";
        failureTransition.addFeature(new EnablingFunction(gateFailTransitionCondition));
        if(root) {
            StringBuilder markingUpdateStringBuilder = new StringBuilder();
            Collection<Place> places = systemPetriNet.getPlaces();
            for(Place place : places){
                if(!place.equals(failurePlace)){
                    markingUpdateStringBuilder.append(place.getName()).append(" = 0 ;");
                }
            }
            String markingUpdateString = markingUpdateStringBuilder.toString();
            failureTransition.addFeature(new PostUpdater(markingUpdateString, systemPetriNet));
        }
        systemPetriNet.addPostcondition(failureTransition,failurePlace);

        resetConditionBuilder.append(" < 1 ");
        String resetCondition = resetConditionBuilder.toString();
        if(!root){
            Transition resetTransition = systemPetriNet.addTransition(gate.getIdentifier() + " _resetTrans ");
            resetTransition.addFeature(StochasticTransitionFeature.newDeterministicInstance(BigDecimal.ZERO));
            resetTransition.addFeature(new Priority(42));
            resetTransition.addFeature(new EnablingFunction(resetCondition));
            systemPetriNet.addPrecondition(failurePlace,resetTransition);
        }
        return failurePlace.getName();
    }

    private static String processKofNGate(PetriNet systemPetriNet, Marking systemMarking, HashMap<String,String> components, KofNGate gate, boolean root) {
        int K = gate.getK();
        List<String> gateFailurePlaces = new ArrayList<>();
        for(Gate entrygate : gate.getGates()){
            String failurePlace = processGate(systemPetriNet,systemMarking,components,entrygate, false);
            gateFailurePlaces.add(failurePlace);
        }

        Set<String> nodeFailurePlaces = new HashSet<>();
        for(ComponentNode node : gate.getNodes()){
            String nodeFailurePlace = createComponentPetriNetCopy(components,systemPetriNet, systemMarking, node);
            nodeFailurePlaces.add(nodeFailurePlace);
        }

        Place failurePlace = systemPetriNet.addPlace(gate.getIdentifier() + "_ORfailure");
        Transition failureTransition = systemPetriNet.addTransition(gate.getIdentifier() + "_failTrans");
        failureTransition.addFeature(StochasticTransitionFeature.newDeterministicInstance(BigDecimal.ZERO));
        failureTransition.addFeature(new Priority(41));
        StringBuilder resetConditionBuilder = new StringBuilder();
        for(String gateFailurePlace : gateFailurePlaces){
            resetConditionBuilder.append("+");
            if(resetConditionBuilder.toString().equals("+")){
                resetConditionBuilder = new StringBuilder(gateFailurePlace + "+");
            }
            resetConditionBuilder.append(gateFailurePlace);
        }
        for(String nodeFailurePlace : nodeFailurePlaces){
            resetConditionBuilder.append("+");
            if(resetConditionBuilder.toString().equals("+")){
                resetConditionBuilder = new StringBuilder(nodeFailurePlace + "+");
            }
            resetConditionBuilder.append(nodeFailurePlace);
        }
        String gateFailTransitionCondition = resetConditionBuilder.toString();
        gateFailTransitionCondition = gateFailTransitionCondition + " >= K && " + failurePlace + " == 0";
        failureTransition.addFeature(new EnablingFunction(gateFailTransitionCondition));
        if(root) {
            StringBuilder markingUpdateStringBuilder = new StringBuilder();
            Collection<Place> places = systemPetriNet.getPlaces();
            for(Place place : places){
                if(!place.equals(failurePlace)){
                    markingUpdateStringBuilder.append(place.getName()).append(" = 0 ;");
                }
            }
            String markingUpdateString = markingUpdateStringBuilder.toString();
            failureTransition.addFeature(new PostUpdater(markingUpdateString, systemPetriNet));
        }
        systemPetriNet.addPostcondition(failureTransition,failurePlace);
        resetConditionBuilder.append(" < K ");
        String resetCondition = resetConditionBuilder.toString();
        if(!root){
            Transition resetTransition = systemPetriNet.addTransition(gate.getIdentifier() + " _resetTrans ");
            resetTransition.addFeature(StochasticTransitionFeature.newDeterministicInstance(BigDecimal.ZERO));
            resetTransition.addFeature(new Priority(42));
            resetTransition.addFeature(new EnablingFunction(resetCondition));
            systemPetriNet.addPrecondition(failurePlace,resetTransition);
        }
        return failurePlace.getName();
    }

    private static String createComponentPetriNetCopy(HashMap<String,String> components, PetriNet systemPetriNet, Marking systemMarking, ComponentNode componentNode) {

        String failurePlaceName;

        if(components.containsKey(componentNode.getName())){
            failurePlaceName = components.get(componentNode.getName());
        }else{
            PetriNet gspnPetriNet = componentNode.getComponentGSPN().getPetriNet();
            Marking gspnMarking = componentNode.getComponentGSPN().getMarking();
            String nodeName = componentNode.getName();

            for(Place place : gspnPetriNet.getPlaces()) {
                systemPetriNet.addPlace(nodeName +"_"+place.getName());
            }
            for(Transition transition : gspnPetriNet.getTransitions()) {
                Transition systemTransition = systemPetriNet.addTransition(nodeName +"_"+transition.getName());

                Collection<TransitionFeature> transitionFeatures =transition.getFeatures();
                for(TransitionFeature transitionFeature : transitionFeatures){
                    systemTransition.addFeature(transitionFeature);
                }

                Collection<InhibitorArc> inhibArcs = gspnPetriNet.getInhibitorArcs(transition);
                for(InhibitorArc arc : inhibArcs) {
                    Place gspnInhibPlace = arc.getPlace();
                    Place systemInhibPlace = systemPetriNet.getPlace(nodeName +"_"+gspnInhibPlace.getName());
                    systemPetriNet.addInhibitorArc(systemInhibPlace,systemTransition);
                }

                Collection<Precondition> preconditions = gspnPetriNet.getPreconditions(transition);
                for(Precondition precondition : preconditions) {
                    Place prePlace = systemPetriNet.getPlace(nodeName+"_"+precondition.getPlace().getName());
                    systemPetriNet.addPrecondition(prePlace, systemTransition);
                }
                Collection<Postcondition> postconditions = gspnPetriNet.getPostconditions(transition);
                for(Postcondition postcondition : postconditions) {
                    Place postPlace = systemPetriNet.getPlace(nodeName+"_"+postcondition.getPlace().getName());
                    systemPetriNet.addPostcondition(systemTransition,postPlace);
                }
            }

            for(String placeName : gspnMarking.getNonEmptyPlacesNames()){
                Place place = systemPetriNet.getPlace(nodeName+"_"+placeName);
                systemMarking.addTokens(place, gspnMarking.getTokens(placeName));
            }

            Place failurePlace = systemPetriNet.addPlace(nodeName +"_failurePlace");
            Transition failureTransition = systemPetriNet.addTransition(nodeName +"_failureTransition");
            String enablingFunctionLimiter = " && " + failurePlace.getName() + " == 0";
            failureTransition.addFeature(new EnablingFunction(nodeName+"_"+componentNode.getFailureCondition()+enablingFunctionLimiter));
            failureTransition.addFeature(StochasticTransitionFeature.newDeterministicInstance(BigDecimal.ZERO));
            failureTransition.addFeature(new Priority(41));
            systemPetriNet.addPostcondition(failureTransition, failurePlace);
            Transition resetTransition = systemPetriNet.addTransition(nodeName +"_resetTransition");
            String complementfailureCondition = nodeName+"_"+ BooleanComplement.complementExpression(componentNode.getFailureCondition());
            resetTransition.addFeature(new EnablingFunction(complementfailureCondition));
            resetTransition.addFeature(StochasticTransitionFeature.newDeterministicInstance(BigDecimal.ZERO));
            resetTransition.addFeature(new Priority(42));
            systemPetriNet.addPrecondition(failurePlace,resetTransition);
            failurePlaceName = failurePlace.getName();
            components.put(componentNode.getName(),failurePlaceName);
        }

        return failurePlaceName;
    }
}

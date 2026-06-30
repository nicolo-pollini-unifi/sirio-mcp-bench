package org.swam.sirio_mcp_server;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.Collection;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.lang.reflect.Field;
import java.lang.reflect.Modifier;

import org.oristool.models.gspn.GSPNSteadyState;
import org.oristool.models.gspn.GSPNTransient;
import org.oristool.models.stpn.MarkingExpr;
import org.oristool.models.stpn.trees.StochasticTransitionFeature;
import org.oristool.models.pn.PetriTokensAdder;
import org.oristool.models.pn.PetriTokensRemover;
import org.oristool.models.pn.Priority;
import org.oristool.petrinet.EnablingFunction;
import org.oristool.petrinet.InhibitorArc;
import org.oristool.petrinet.Marking;
import org.oristool.petrinet.PetriNet;
import org.oristool.petrinet.Place;
import org.oristool.petrinet.Postcondition;
import org.oristool.petrinet.Precondition;
import org.oristool.petrinet.Transition;
import org.oristool.petrinet.TransitionFeature;
import org.oristool.util.Pair;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.stereotype.Service;
import org.swam.pn_utils.PetriNetUtils;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.MapperFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;

@Service
public class SirioService {

    // --------------------------
    // Attributes
    // --------------------------
    private PetriNet petriNet = null;
    private Marking marking = null;

    ObjectMapper om = new ObjectMapper().configure(MapperFeature.SORT_PROPERTIES_ALPHABETICALLY, true);

    @Tool(name = "create", description = "Create an empty petri net with an empty marking")
    public void createPetriNet() {
        petriNet = new PetriNet();
        marking = new Marking();
    }

    // --------------------------
    // Places
    // --------------------------

    @Tool(name = "add_places", description = "Add new places to the net")   // TODO: aggiungere nella descrizione che il nome dei place non può contenere spazi. Alternativamente, gestire i nomi con spazi, sostituendoli con underscore o simili
    public void addPlaces(
        @ToolParam(description = "List of place names") List<String> node_names) {
        PetriNetUtils.checkNetAndMarking(petriNet, marking);
        for (String nodeName : node_names) {
            petriNet.addPlace(nodeName);
        }
    }

    @Tool(name = "remove_places", description = "Remove existent places from the net")  // TODO: aggiungere nella descrizione che può rimuovere anche gli archi collegati
    public void removePlaces(
        @ToolParam(description = "List of place names") List<String> node_names) {
        PetriNetUtils.checkNetAndMarking(petriNet, marking);
        petriNet.getTransitions().stream()
                .map(petriNet::getPreconditions)
                .flatMap(Collection::stream)
                .filter(p -> node_names.contains(p.getPlace().getName()))
                .forEach(petriNet::removePrecondition);

        petriNet.getTransitions().stream()
                .map(petriNet::getPostconditions)
                .flatMap(Collection::stream)
                .filter(p -> node_names.contains(p.getPlace().getName()))
                .forEach(petriNet::removePostcondition);

        node_names.stream()
                .map(petriNet::getPlace)
                .filter(java.util.Objects::nonNull)
                .forEach(petriNet::removePlace);
    }

    // --------------------------
    // Transitions
    // --------------------------

    @Tool(name = "add_transitions", description = "Add new transitions to the net")
    public void addTransitions(
        @ToolParam(description = "List of transition names") List<String> transition_names) {
        PetriNetUtils.checkNetAndMarking(petriNet, marking);
        for (String transitionName : transition_names) {
            petriNet.addTransition(transitionName);
        }
    }

    @Tool(name = "remove_transitions", description = "Remove existent transitions from the net")
    public void removeTransitions(
        @ToolParam(description = "List of transition names") List<String> transition_names) {
        PetriNetUtils.checkNetAndMarking(petriNet, marking);
        transition_names.stream()
                .map(petriNet::getTransition)
                .filter(java.util.Objects::nonNull)
                .forEach(transition -> {
                        petriNet.getPreconditions(transition)
                                .forEach(petriNet::removePrecondition);
                        petriNet.getPostconditions(transition)
                                .forEach(petriNet::removePostcondition);
                        petriNet.getInhibitorArcs(transition)
                                .forEach(petriNet::removeInhibitorArc);
                        petriNet.removeTransition(transition);
                });
    }

    @Tool(name = "add_UNI", description = "Add a new uniformely distributed transition with specified earliest and latest firing times, optionally with a scaling clock rate")
    public void addUNI(
            @ToolParam(description = "name of transition") String transition_name,
            @ToolParam(description = "earliest firing time") double eft,
            @ToolParam(description = "latest firing time") double lft,
            @ToolParam(description = "Optional scaling rate value. If not valid, the model will provide an explanation and clarify the problem and how to solve it", required = false) Double clockRate) {
        PetriNetUtils.checkNetAndMarking(petriNet, marking);
        Transition t = PetriNetUtils.findOrCreateTransitionByName(petriNet, transition_name);
        t.addFeature(StochasticTransitionFeature.newUniformInstance(BigDecimal.valueOf(eft), BigDecimal.valueOf(lft),
                clockRate != null ? MarkingExpr.of(clockRate) : MarkingExpr.ONE));
    }

    @Tool(name = "add_DET", description = "Add a new transition with a deterministic timer, optionally with a scaling clock rate and weight")
    public void addDET(
            @ToolParam(description = "name of transition") String transition_name,
            @ToolParam(description = "timer value") double value,
            @ToolParam(description = "Optional scaling rate value. If not valid, the model will provide an explanation and clarify the problem and how to solve it", required = false) Double clockRate,
            @ToolParam(description = "Optional weight of the transition", required = false) Double weight) {
        PetriNetUtils.checkNetAndMarking(petriNet, marking);
        Transition t = PetriNetUtils.findOrCreateTransitionByName(petriNet, transition_name);

        t.addFeature(StochasticTransitionFeature.newDeterministicInstance(BigDecimal.valueOf(value),
                weight != null ? MarkingExpr.of(weight) : MarkingExpr.ONE,
                clockRate != null ? MarkingExpr.of(clockRate) : MarkingExpr.ONE));
    }

    @Tool(name = "add_IMM", description = "Add a new immediate transition")
    public void addIMM(
            @ToolParam(description = "name of transition") String transition_name) {
        PetriNetUtils.checkNetAndMarking(petriNet, marking);
        Transition t = PetriNetUtils.findOrCreateTransitionByName(petriNet, transition_name);

        t.addFeature(StochasticTransitionFeature.newDeterministicInstance("0"));
    }

    @Tool(name = "add_EXP", description = "Add a new transition with a exponential timer and variable rate, optionally with clockRate and weight")
    public void addEXP(
            @ToolParam(description = "name of transition") String transition_name,
            @ToolParam(description = "rate value") double rate,
            @ToolParam(description = "Optional scaling rate value. If not valid, the model will provide an explanation and clarify the problem and how to solve it", required = false) Double clockRate,
            @ToolParam(description = "Optional weight of the transition", required = false) Double weight) {
        PetriNetUtils.checkNetAndMarking(petriNet, marking);
        Transition t = PetriNetUtils.findOrCreateTransitionByName(petriNet, transition_name);

        t.addFeature(StochasticTransitionFeature.newExponentialInstance(BigDecimal.valueOf(rate),
                (clockRate != null) ? MarkingExpr.of(clockRate) : MarkingExpr.ONE,
                (weight != null) ? MarkingExpr.of(weight) : MarkingExpr.ONE // If weight is provided, clockRate must be provided too, as per function signature
        ));
    }

    @Tool(name = "set_transition_priority", description = "Set the priority of a specific transition")
    public void setTransitionPriority(
            @ToolParam(description = "name of transition") String transition_name,
            @ToolParam(description = "priority value") int priority) {
        PetriNetUtils.checkNetAndMarking(petriNet, marking);
        Transition t = PetriNetUtils.findOrCreateTransitionByName(petriNet, transition_name);
        if (priority < 0) {
            throw new IllegalArgumentException("Priority must be a non-negative integer.");
        }
        t.removeFeature(Priority.class); // Rimuove eventuali priorità esistenti
        t.addFeature(new Priority(priority));
    }

    // --------------------------
    // Petri Net manipulation
    // --------------------------

    @Tool(name = "show_net", description = "Show the current status of the Petri Net")
    public String showPetriNet() {
        PetriNetUtils.checkNetAndMarking(petriNet, marking);
        return petriNet.toString() + "\n" + marking.toString();
    }

    @Tool(name = "reset_marking", description = "Reset the current marking of the system to empty")
    public void resetMarking() {
        marking = new Marking();
    }

    @Tool(name = "add_tokens", description = "Add a specific number of tokens to a place")
    public void addToken(
            @ToolParam(description = "Name of the place") String name,
            @ToolParam(description = "Number of tokens to be added") int num) {
        PetriNetUtils.checkNetAndMarking(petriNet, marking);
        Place p = PetriNetUtils.findPlaceByName(petriNet, name);

        marking.addTokens(p, num);
    }

    @Tool(name = "remove_tokens", description = "Remove a specific number of tokens from a place")
    public void removeToken(
            @ToolParam(description = "Name of the place") String name,
            @ToolParam(description = "Number of tokens to be removed") int num) {
        PetriNetUtils.checkNetAndMarking(petriNet, marking);
        Place p = PetriNetUtils.findPlaceByName(petriNet, name);

        marking.removeTokens(p, num);
    }

    @Tool(name = "add_enabling_function", description = "Add an enabling function to a transition")
    public void addEnablingFunction(
            @ToolParam(description = "Condition of the enabling function, boolean expression as String (ex. 'place_name == 1')") String condition,
            @ToolParam(description = "Transition to apply the enabling function to") String transition_name) {
        PetriNetUtils.checkNetAndMarking(petriNet, marking);
        Transition target = PetriNetUtils.findTransitionByName(petriNet, transition_name);

        target.addFeature(new EnablingFunction(condition));
    }

    @Tool(name = "get_enabled_transitions", description = "Get a list of transitions that are currently enabled and can be fired")
    public List<String> getEnabledTransitions() {
        PetriNetUtils.checkNetAndMarking(petriNet, marking);
        return petriNet.getEnabledTransitions(marking).stream()
                .map(Transition::getName)
                .collect(java.util.stream.Collectors.toList());
    }

    @Tool(name = "fire_transition", description = "Fires a specific transition to advance the marking (Token Game). Updates the current marking of the system")
    public String fireTransition(
            @ToolParam(description = "Name of the transition to fire") String transition_name) {
        PetriNetUtils.checkNetAndMarking(petriNet, marking);
        Transition t = PetriNetUtils.findTransitionByName(petriNet, transition_name);

        if (!petriNet.isEnabled(t, marking)) { // Controllo che la transizione sia attiva
            throw new IllegalArgumentException(
                    "Transition " + transition_name + " is not enabled in the current marking.");
        }

        PetriTokensAdder pta = new PetriTokensAdder();
        pta.update(marking, petriNet, t);

        PetriTokensRemover ptr = new PetriTokensRemover();
        ptr.update(marking, petriNet, t);

        return marking.toString();
    }

    @Tool(name = "get_transition_features", description = "Retrieves all features and parameters of a specific transition using deep reflection.")
    public String getTransitionFeatures(
            @ToolParam(description = "The name of the transition to inspect") String transition_name) {
        PetriNetUtils.checkNetAndMarking(petriNet, marking);
        Transition t = PetriNetUtils.findTransitionByName(petriNet, transition_name);
        StringBuilder output = new StringBuilder();
        output.append("=== Features for transition '").append(transition_name).append("' ===\n");

        if (t.getFeatures().isEmpty()) {
            output.append("No features found (Standard Immediate Transition).\n");
            return output.toString();
        }

        // CICLO UNICO PER TUTTE LE FEATURE
        for (var feature : t.getFeatures()) {
            Class<?> featureClass = feature.getClass();
            String simpleName = featureClass.getSimpleName();

            output.append("\n[").append(simpleName).append("]\n");

            // SE È LA FEATURE STOCASTICA, VOGLIAMO VEDERE DENTRO LA 'density'
            // Questo è l'unico "if" speciale, perché la struttura di Sirio annida la
            // distribuzione
            if (feature instanceof StochasticTransitionFeature) {
                StochasticTransitionFeature stf = (StochasticTransitionFeature) feature;
                var density = stf.density();

                output.append("  > Distribution Type: ").append(density.getClass().getSimpleName()).append("\n");

                // Ispeziona i campi dell'oggetto DENSITY (es. rate, eft, lft)
                printAllFields(density, output, "    - ");

                //TODO aggiungere stampa di DENSITY e altri parametri rilevanti
                // Stampa anche i campi base della feature (weight, clockRate)
                output.append("  > Base Parameters:\n");
                output.append("    - Weight: ").append(stf.weight()).append("\n");
                output.append("    - ClockRate: ").append(stf.clockRate()).append("\n");

            } else {
                // PER QUALSIASI ALTRA FEATURE (EnablingFunction, Priority, ecc.)
                // Ispeziona direttamente i suoi campi
                printAllFields(feature, output, "  - ");
            }
        }

        return output.toString();
    }

    // Metodo helper per stampare i campi via Reflection
    private void printAllFields(Object obj, StringBuilder output, String prefix) {
        Class<?> objClass = obj.getClass();
        // Prende tutti i campi, inclusi quelli privati
        Field[] fields = objClass.getDeclaredFields();

        if (fields.length == 0) {
            // Se non ha campi, stampiamo il toString() come fallback
            output.append(prefix).append("Value: ").append(obj.toString()).append("\n");
            return;
        }

        for (Field field : fields) {
            try {
                // TODO va trovato un modo per accedere al campo 'domain' in modo da vedere eft e lft
                // field.setAccessible(true); // HACK "Scassina" i campi privati

                // Saltiamo i campi statici o costanti inutili
                if (Modifier.isStatic(field.getModifiers())) {
                    continue;
                }

                String name = field.getName();
                Object value = field.get(obj);

                output.append(prefix).append(name).append(": ").append(value).append("\n");

            } catch (Exception e) {
                // Ignora errori di accesso
            }
        }
    }

    // --------------------------
    // Preconditions, Postconditions and Inhibitor Arcs
    // --------------------------
    @Tool(name = "add_precondition", description = "Add a precondition to a transition")
    public void addPrecondition(
            @ToolParam(description = "Name of the place") String place_name,
            @ToolParam(description = "Name of the transition") String transition_name) {
        PetriNetUtils.checkNetAndMarking(petriNet, marking);
        Place p = PetriNetUtils.findPlaceByName(petriNet, place_name);
        Transition t = PetriNetUtils.findTransitionByName(petriNet, transition_name);

        petriNet.addPrecondition(p, t);
    }

    @Tool(name = "remove_preconditions", description = "Remove a precondition to a transition")
    public void removePrecondition(
            @ToolParam(description = "Name of the place") String place_name,
            @ToolParam(description = "Name of the transition") String transition_name) {
        PetriNetUtils.checkNetAndMarking(petriNet, marking);
        Place p = PetriNetUtils.findPlaceByName(petriNet, place_name);
        Transition t = PetriNetUtils.findTransitionByName(petriNet, transition_name);

        Precondition pc = petriNet.getPrecondition(p, t);
        petriNet.removePrecondition(pc);
    }

    @Tool(name = "add_postcondition", description = "Add a postcondition to a transition")
    public void addPostcondition(
            @ToolParam(description = "Name of the transition") String transition_name,
            @ToolParam(description = "Name of the place") String place_name) {
        PetriNetUtils.checkNetAndMarking(petriNet, marking);
        Transition t = PetriNetUtils.findTransitionByName(petriNet, transition_name);
        Place p = PetriNetUtils.findPlaceByName(petriNet, place_name);

        petriNet.addPostcondition(t, p);
    }

    @Tool(name = "remove_postconditions", description = "Remove a postcondition to a transition")
    public void removePostcondition(
            @ToolParam(description = "Name of the place") String place_name,
            @ToolParam(description = "Name of the transition") String transition_name) {
        PetriNetUtils.checkNetAndMarking(petriNet, marking);
        Transition t = PetriNetUtils.findTransitionByName(petriNet, transition_name);
        Place p = PetriNetUtils.findPlaceByName(petriNet, place_name);

        Postcondition pc = petriNet.getPostcondition(t, p);
        petriNet.removePostcondition(pc);
    }

    @Tool(name = "add_inhibitor_arc", description = "Add an inhibitor arc between a place and a transition")
    public void addInhibitorArc(
            @ToolParam(description = "Name of the source place") String source_name,
            @ToolParam(description = "Name of the target transition") String transition_name) {
        PetriNetUtils.checkNetAndMarking(petriNet, marking);
        Place source = PetriNetUtils.findPlaceByName(petriNet, source_name);
        Transition target = PetriNetUtils.findTransitionByName(petriNet, transition_name);

        petriNet.addInhibitorArc(source, target);
    }

    @Tool(name = "remove_inhibitor_arc", description = "Remove an inhibitor arc between a place and a transition")
    public void removeInhibitorArc(
            @ToolParam(description = "Name of the place") String place_name,
            @ToolParam(description = "Name of the transition") String transition_name) {
        PetriNetUtils.checkNetAndMarking(petriNet, marking);
        Place p = PetriNetUtils.findPlaceByName(petriNet, place_name);
        Transition t = PetriNetUtils.findTransitionByName(petriNet, transition_name);

        InhibitorArc ia = petriNet.getInhibitorArc(p, t);
        petriNet.removeInhibitorArc(ia);
    }

    // --------------------------
    // Analysis
    // --------------------------

    @Tool(name = "execute_steady_state_analysis", description = "Executes a steady state analysis on a generalized stochastic petri net. This requires all the transitions to be immediate (with firing time deterministic and equal to 0) or exponential (with firing time distributed as an exponential random variable with rate lambda)")
    public String executeSteadyStateAnalysis() {
        PetriNetUtils.checkNetAndMarking(petriNet, marking);
        Map<Marking, Double> result = GSPNSteadyState.builder().build().compute(petriNet, marking);
        String stringResult = "";
        try {
            stringResult = om.writeValueAsString(result);
        } catch (JsonProcessingException e) {
            return stringResult;
        }
        return stringResult;
    }

    @Tool(name = "execute_transient_analysis", description = "Executes a transient analysis on a generalized stochastic petri net at specific time points. This requires all the transitions to be immediate (with firing time deterministic and equal to 0) or exponential (with firing time distributed as an exponential random variable with rate lambda) and either a list of time points or a time range (start, end, step). Returns the probability distribution over markings at each specified time point.")
    public String executeTransientAnalysis(
            @ToolParam(description = "A list of time points to compute probabilities for (e.g., [1.0, 5.0, 10.0]) or a time range (start, end, step) (e.g. given [0.0, 2.0, 0.2], the resulting time points will be [0.0, 0.2, 0.4, 0.6, 0.8, 1.0, 1.2, 1.4, 1.6, 1.8, 2.0])") List<Double> timePoints) {
        PetriNetUtils.checkNetAndMarking(petriNet, marking);
        if (petriNet == null || marking == null) {
            throw new IllegalStateException("Petri net and marking must be created before running analysis.");
        }

        // Il GSPNTransient.builder accetta un array di double[] --> Converto la lista di Double in un array di double
        double[] timePointsArray = timePoints.stream()
                .mapToDouble(Double::doubleValue)
                .toArray();

        // Creo l'analizzatore ed eseguo i calcoli
        Pair<Map<Marking, Integer>, double[][]> result = GSPNTransient.builder()
                .timePoints(timePointsArray) // Costruisce l'analizzatore
                .build().compute(petriNet, marking); // Esegue il calcolo

        // Estraggo i risultati
        Map<Marking, Integer> statePos = result.first();
        double[][] probs = result.second(); // [indice_tempo][indice_stato]

        //TODO ritestare questa parte con una linkedList o simili per mantenere l'ordine

        Map<Double, Map<Marking, Double>> transientResults = new HashMap<>();

        // Ciclo principale sugli istanti di tempo (corrispondenti alle righe della matrice)
        for (int t_idx = 0; t_idx < timePointsArray.length; t_idx++) {
            double currentTime = timePointsArray[t_idx];
            Map<Marking, Double> probsAtThisTime = new HashMap<>();

            // Per ogni istante, estraiamo le probabilità di tutti gli stati
            for (Map.Entry<Marking, Integer> entry : statePos.entrySet()) {
                Marking m = entry.getKey();
                int state_idx = entry.getValue(); // Indice di colonna

                if (t_idx < probs.length && state_idx < probs[t_idx].length) {
                    double prob = probs[t_idx][state_idx];
                    probsAtThisTime.put(m, prob); // Potrei mettere un controllo prob > 0.0 per pulire l'output?
                }
            }
            transientResults.put(currentTime, probsAtThisTime);
        }
        String tResults = "";
        try {
            tResults = om.writeValueAsString(transientResults);
        } catch (JsonProcessingException e) {
            return tResults;
        }
        return tResults;
    }
}

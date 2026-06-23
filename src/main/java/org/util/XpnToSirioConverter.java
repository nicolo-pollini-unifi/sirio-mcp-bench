package org.util;

import org.oristool.models.stpn.trees.StochasticTransitionFeature;
import org.oristool.petrinet.Marking;
import org.oristool.petrinet.PetriNet;
import org.oristool.petrinet.Place;
import org.oristool.petrinet.Transition;
import org.w3c.dom.*;

import javax.xml.parsers.DocumentBuilder;
import javax.xml.parsers.DocumentBuilderFactory;
import java.io.File;
import java.math.BigDecimal;
import java.util.HashMap;
import java.util.Map;

public class XpnToSirioConverter {

    private PetriNet petriNet;
    private Marking marking;
    private HashMap<Transition, Double> transitionRates;

    public XpnToSirioConverter() {
        transitionRates = new HashMap<>();
    }

    public PetriNet getPetriNet() {
        return petriNet;
    }

    public HashMap<Transition, Double> getTransitionRates() {
        return transitionRates;
    }

    public Marking getMarking(){
        return marking;
    }

    public void convertXPNtoPetriNet(String filePath) {
        try {
            File file = new File(filePath);
            DocumentBuilderFactory factory = DocumentBuilderFactory.newInstance();
            DocumentBuilder builder = factory.newDocumentBuilder();
            Document document = builder.parse(file);
            document.getDocumentElement().normalize();

            petriNet = new PetriNet();
            marking = new Marking();
            Map<String, Place> placesMap = new HashMap<>();
            Map<String, Transition> transitionsMap = new HashMap<>();

            NodeList placeNodes = document.getElementsByTagName("place");
            for (int i = 0; i < placeNodes.getLength(); i++) {
                Element placeElement = (Element) placeNodes.item(i);
                String uuid = placeElement.getAttribute("uuid");
                String name = "";
                int tokens = 0;

                NodeList properties = placeElement.getElementsByTagName("property");
                for (int j = 0; j < properties.getLength(); j++) {
                    Element prop = (Element) properties.item(j);
                    if ("0.default.name".equals(prop.getAttribute("id"))) {
                        name = prop.getAttribute("name");
                    } else if ("default.marking".equals(prop.getAttribute("id"))) {
                        String markingStr = prop.getAttribute("marking");
                        tokens = markingStr.isEmpty() ? 0 : Integer.parseInt(markingStr);
                    }
                }

                Place place = petriNet.addPlace(name);
                placesMap.put(uuid, place);
                if (tokens > 0) {
                    marking.setTokens(place, tokens);
                }
            }

            NodeList transitionNodes = document.getElementsByTagName("transition");
            for (int i = 0; i < transitionNodes.getLength(); i++) {
                Element transitionElement = (Element) transitionNodes.item(i);
                String uuid = transitionElement.getAttribute("uuid");
                String name = "";

                Map<String, Map<String, String>> propertiesMap = new HashMap<>();

                NodeList properties = transitionElement.getElementsByTagName("property");
                for (int j = 0; j < properties.getLength(); j++) {
                    Element prop = (Element) properties.item(j);
                    String propId = prop.getAttribute("id");

                    if ("0.default.name".equals(propId)) {
                        name = prop.getAttribute("name");
                    }

                    NamedNodeMap attributes = prop.getAttributes();
                    Map<String, String> attrMap = new HashMap<>();
                    for (int k = 0; k < attributes.getLength(); k++) {
                        Node attr = attributes.item(k);
                        attrMap.put(attr.getNodeName(), attr.getNodeValue());
                    }

                    propertiesMap.put(propId, attrMap);

                    if (propId.equals("transition.stochastic")) {
                        String lambda = prop.getAttribute("lambda");
                        String dataType = prop.getAttribute("property-data-type");
                        if(dataType.equals("3.type.exponential")){
                            Transition transition = petriNet.addTransition(name);
                            transition.addFeature(StochasticTransitionFeature.newExponentialInstance(lambda));
                            transitionsMap.put(uuid, transition);
                            transitionRates.put(transition, Double.valueOf(lambda));
                        }

                        if(dataType.equals("4.type.erlang")){
                            String k = prop.getAttribute("k");
                            Transition transition = petriNet.addTransition(name);
                            int kValue = Integer.parseInt(k);
                            BigDecimal lambdaValue = BigDecimal.valueOf(Double.parseDouble(lambda));
                            transition.addFeature(StochasticTransitionFeature.newErlangInstance(kValue,lambdaValue));
                            transitionsMap.put(uuid, transition);
                            transitionRates.put(transition, Double.valueOf(lambda));
                        }
                        //TODO Add all properties
                    }
                }
            }

            // Parsing degli Archi
            NodeList arcNodes = document.getElementsByTagName("arc");
            for (int i = 0; i < arcNodes.getLength(); i++) {
                Element arcElement = (Element) arcNodes.item(i);
                String from = arcElement.getAttribute("from");
                String to = arcElement.getAttribute("to");

                // Cerca se è un arco da place a transition
                if (placesMap.containsKey(from) && transitionsMap.containsKey(to)) {
                    petriNet.addPrecondition(placesMap.get(from), transitionsMap.get(to));
                }
                // oppure da transition a place
                else if (transitionsMap.containsKey(from) && placesMap.containsKey(to)) {
                    petriNet.addPostcondition(transitionsMap.get(from), placesMap.get(to));
                }
            }

            // Output di verifica
            System.out.println("Petri Net creata con successo!");
            System.out.println("Luoghi: " + petriNet.getPlaces());
            System.out.println("Transizioni: " + petriNet.getTransitions());
            System.out.println("Marking iniziale: " + marking);

        } catch (Exception e) {
            e.printStackTrace();
        }
    }
}
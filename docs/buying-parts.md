# Buying components

A shopping list for the board, grouped the way you shop, with a search link at the shop of your choice on every line: four big distributors and four pedal-parts shops.

Open it with **Order › Buy components…** (Ctrl+Shift+B), the **Buy parts** toolbar button, or the **Buy components** card on the Order & Manufacture tab.

![Buy components with Tayda Electronics selected](media/img/buy-parts.webp)

## The shopping list

Every part on the board, grouped into resistors; film, ceramic and electrolytic capacitors; diodes and LEDs; transistors and ICs; pots; switches; connectors and hardware. Pedal designs also get the enclosure hardware (the box, knobs, footswitch, jacks and DC socket) and IC sockets for the DIP chips.

Each line has the quantity, the value, the package, the designators, the part number if the part has one, and the words to search for. **Build** multiplies the quantities, for building several.

## Where to buy

| Shop | Where | Good for |
|---|---|---|
| **Digi-Key** | USA, ships worldwide | A huge in-stock catalogue, fast shipping, no minimum order. Upload a BOM to myLists as a guest. |
| **Mouser** | USA, ships worldwide | A huge in-stock catalogue and fast shipping. The BOM tool needs a free My Mouser account. |
| **LCSC** | China, ships worldwide | Very low prices. The same C-numbers as JLCPCB assembly, so parts with an LCSC number open their exact product page. |
| **Farnell / element14** | UK and Europe (Newark in the US) | A broad catalogue with next-day delivery in the UK and Europe |
| **Tayda Electronics** | Thailand, with a US warehouse | The pedal builder's staple: cheap passives, Alpha pots, enclosures, plus custom drilling and UV printing |
| **Small Bear Electronics** | USA | Pedal specialist: footswitches, jacks, enclosures, vintage and germanium transistors |
| **Love My Switches** | USA | Pedal hardware: footswitches, toggles, pots, knobs, LEDs and enclosures |
| **Das Musikding** | Germany, ships across the EU | EU pedal-parts shop: enclosures, pots, switches, knobs and kits |

## Finding each part

**Find ↗** on a line searches the selected shop for it, in your browser. **Find selected lines** opens several at once.

The search words are catalogue-style on purpose: `4.7K 1/4W metal film`, `25K linear potentiometer`, `125B enclosure`. The hobby shops' search only returns products that contain every word, so "B25K 16mm" finds nothing on Tayda while "B25K" finds the Alpha pots. You can edit the words on any line. A part with a manufacturer part number is searched by it, and a part with an LCSC number opens its exact LCSC product page.

## Uploading a parts list

**Upload parts list…** saves `<name>_parts_order.csv` in the project's `_fab` folder and opens the shop's BOM tool, where you import it to fill a cart. This works with Digi-Key myLists, Mouser (with an account) and LCSC.

**Copy list** puts the list on the clipboard as text, and **Save list…** saves it as CSV or text, for any other shop or for your notes.

## Have Tayda drill the enclosure

For pedal designs, **Export holes & open drill service** exports the enclosure's hole coordinates in Tayda's format (side, mm from the centre of each side) and opens Tayda's drill designer, where you add them and order the box drilled, and UV-printed if you like. See [Guitar pedals](pedals.md#drill-outputs).

## Shop and fab links

**Order › Component supplier websites** and **Order › PCB manufacturer websites** link straight to every shop and fab, including Tayda's drilling service.

Nothing here talks to a shop in the background. PCBPro builds links that open in your browser and CSV files that the shops' own BOM tools import. The links were checked against each site in September 2026; if a shop changes its search, a pull request to `pcbpro/fab/suppliers.py` fixes it for everyone.
